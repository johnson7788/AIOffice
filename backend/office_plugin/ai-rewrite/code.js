(function (window) {
  // 后端意图解析端点。插件在用户浏览器里运行，localhost 指向用户机器上的后端。
  // ponytail: 生产/容器部署时改成可达的后端地址（可由 config 注入）
  var BACKEND = "http://localhost:8585/office/edit";

  var selText = "";
  var selEl, instEl, goEl, statusEl;

  function setStatus(s) { if (statusEl) statusEl.textContent = s || ""; }

  // 打开插件时 ONLYOFFICE 把当前选区文本作为 initData 传入（config.initDataType=text）
  window.Asc.plugin.init = function (text) {
    selText = text || "";
    selEl = document.getElementById("sel");
    instEl = document.getElementById("inst");
    goEl = document.getElementById("go");
    statusEl = document.getElementById("status");
    selEl.textContent = selText || "（未选中，可做整篇/整页操作）";
    goEl.onclick = onApply;
  };

  function docType() {
    // word / cell / slide —— 让后端 LLM 知道可用哪些操作
    var info = window.Asc.plugin.info || {};
    return info.editorType || "slide";
  }

  function onApply() {
    var instruction = (instEl.value || "").trim();
    if (!instruction) { setStatus("请输入编辑指令"); return; }
    goEl.disabled = true;
    setStatus("解析中…");
    fetch(BACKEND, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: selText, instruction: instruction, doc_type: docType() }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.op) throw new Error(data && data.error ? data.error : "空返回");
        applyOp(data.op);
      })
      .catch(function (e) {
        setStatus("失败：" + (e.message || e));
        goEl.disabled = false;
      });
  }

  // op → Builder 操作。回写后由 ONLYOFFICE 自身 forcesave→后端 callback 落盘（沿用 P2）。
  function applyOp(op) {
    var done = function (msg) { setStatus(msg); goEl.disabled = false; };
    if (op.type === "replace_selection") {
      // 替换当前选区文本
      window.Asc.plugin.executeMethod("PasteText", [op.text], function () {
        selText = op.text; selEl.textContent = selText; done("已替换选区");
      });
      return;
    }
    // 全文/整页操作走 callCommand（Builder API 在 live 文档模型里执行）
    // 参数经 Asc.scope 传进 callCommand（函数体被序列化，无法闭包捕获 op）
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
      } else if (op.type === "replace_text") {
        // 仅文本文档：全文查找替换
        Api.GetDocument().SearchAndReplace({ searchString: op.find, replaceString: op.replace });
      }
    }, false, false, function () {
      done("已应用：" + op.type);
    });
  }

  window.Asc.plugin.button = function () {
    window.Asc.plugin.executeCommand("close", "");
  };
})(window);
