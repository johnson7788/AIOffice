(function (window) {
  // P6.3 broker 桥·插件后台常驻端：轮询后端信箱，取走助手侧栏经 agent 投递的 op，
  // 用 callCommand（Builder API）在 live 会话里落地。这样助手侧栏无需跨 iframe 就能改文档。
  // ponytail: localhost 指向用户机器上的后端；容器/生产部署改成可达地址。
  var BACKEND = "http://localhost:8585/office/pending";
  var POLL_MS = 2000;

  function userId() {
    // 后端 /office/config 把 editorConfig.user.id 设为 user_id；插件读得到就多用户可用，
    // 读不到退回 default_user（本地单用户够用）。
    // ponytail: 多用户上线时确认 Asc.plugin.info.userId 能拿到，否则改由前端把 user_id 传进插件。
    var info = window.Asc.plugin.info || {};
    return info.userId || "default_user";
  }

  // 后台没有选区上下文，只处理「整页/整篇/按坐标寻址」的 callCommand 类 op。
  var CALLCMD_OPS = {
    set_slide_background: 1, set_slide_text: 1, set_cell: 1, replace_text: 1,
  };

  function applyOp(op) {
    if (!CALLCMD_OPS[op.type]) return;
    console.log("[ai-bridge] applyOp " + JSON.stringify(op));
    window.Asc.scope = window.Asc.scope || {};
    window.Asc.scope.op = op;
    window.Asc.plugin.callCommand(function () {
      var op = Asc.scope.op;
      if (op.type === "set_slide_background") {
        var c = op.color;
        var r = parseInt(c.substr(1, 2), 16),
            g = parseInt(c.substr(3, 2), 16),
            b = parseInt(c.substr(5, 2), 16);
        var oSlide = Api.GetPresentation().GetSlideByIndex(op.slide);
        if (oSlide) oSlide.SetBackground(Api.CreateSolidFill(Api.CreateRGBColor(r, g, b)));
      } else if (op.type === "set_slide_text") {
        // 改第 slide 页第 shape 个形状的文字：清空其内容再塞一段新文本
        var oSlide2 = Api.GetPresentation().GetSlideByIndex(op.slide);
        if (oSlide2) {
          var shapes = oSlide2.GetAllShapes();
          var sh = shapes[op.shape];
          if (sh && sh.GetDocContent) {
            var oContent = sh.GetDocContent();
            oContent.RemoveAllElements();
            var oP = Api.CreateParagraph();
            oP.AddText(op.text);
            oContent.Push(oP);
          }
        }
      } else if (op.type === "set_cell") {
        // 给单元格/区域填值（value 恒为字符串，数字/公式由引擎按格式解析）
        Api.GetActiveSheet().GetRange(op.cell).SetValue(op.value);
      } else if (op.type === "replace_text") {
        Api.GetDocument().SearchAndReplace({ searchString: op.find, replaceString: op.replace });
      }
    }, false, false, function () { console.log("[ai-bridge] callCommand done"); });
  }

  // 反向桥：把用户当前选区（文本 + 位置标签）上报后端，助手侧栏轮询取来预填聊天输入框。
  var SEL_BACKEND = "http://localhost:8585/office/selection";
  var SEL_POLL_MS = 800;
  var lastSel = null;

  function editorType() {
    var info = window.Asc.plugin.info || {};
    return info.editorType || "";
  }

  function postSel(text, page) {
    fetch(SEL_BACKEND, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId(), text: text, page: page, editor_type: editorType() }),
    }).catch(function () { /* 后端不可达时静默 */ });
  }

  function reportSelection() {
    var et = editorType();
    if (et === "cell") {
      // 表格：GetSelectedText 取不到单元格内容（返回恒空），改用 callCommand 读活动单元格
      // 地址+值。用「地址\x01值」当变化签名：换格子/改值都触发；选空格子只带地址、值为空。
      window.Asc.plugin.callCommand(function () {
        try {
          var cell = Api.GetActiveSheet().GetActiveCell();
          return cell.GetAddress(false, false, "xlA1") + "\u0001" + (cell.GetValue() || "");
        } catch (e) { return ""; }
      }, false, false, function (res) {
        res = res || "";
        if (res === lastSel) return;
        lastSel = res;
        var i = res.indexOf("\u0001");
        postSel(i < 0 ? "" : res.substr(i + 1), i < 0 ? "" : res.substr(0, i));
      });
      return;
    }
    if (et === "slide") {
      // 幻灯片：选中文本走 GetSelectedText，页码走 callCommand(GetCurSlideIndex)。
      // 本版 docserver 的 Builder API 无法读"选中的图片/形状"（GetSelectedShapes 等皆 noMethod），
      // 所以对图片/形状这类无文本选中，退化为「只带页码、文本空」——点图片时输入框至少更新到"第N页"。
      // 签名用「页码\x01文本」：切页 / 换选区都触发。ponytail: 引擎日后开放选中形状 API 再补形状描述。
      window.Asc.plugin.executeMethod("GetSelectedText", [], function (text) {
        text = text || "";
        window.Asc.plugin.callCommand(function () {
          try { return "第" + (Api.GetPresentation().GetCurSlideIndex() + 1) + "页"; } catch (e) {}
          return "";
        }, false, false, function (page) {
          page = page || "";
          var sig = page + "\u0001" + text;
          if (sig === lastSel) return;
          lastSel = sig;
          postSel(text, page);
        });
      });
      return;
    }
    // word：选中文本靠 GetSelectedText。
    window.Asc.plugin.executeMethod("GetSelectedText", [], function (text) {
      text = text || "";
      if (text === lastSel) return;          // 无变化不上报（含连续空）
      lastSel = text;
      postSel(text, "");
    });
  }

  function poll() {
    fetch(BACKEND + "?user_id=" + encodeURIComponent(userId()))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var ops = (data && data.ops) || [];
        for (var i = 0; i < ops.length; i++) applyOp(ops[i]);
      })
      .catch(function () { /* 后端不可达时静默重试 */ });
  }

  window.Asc.plugin.init = function () {
    setInterval(poll, POLL_MS);
    setInterval(reportSelection, SEL_POLL_MS);
  };

  window.Asc.plugin.button = function () {};
})(window);
