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
  };

  window.Asc.plugin.button = function () {};
})(window);
