/**
 * チャット送信UI制御
 * HTMX イベント委譲パターンで、動的に差し替わるフォームにも対応する。
 * フォームに data-chat-form 属性があればチャットフォームとして扱う。
 */
(function () {
  function isChatForm(form) {
    return form && form.hasAttribute("data-chat-form");
  }

  document.body.addEventListener("htmx:beforeRequest", function (evt) {
    var form = evt.detail.elt;
    if (!isChatForm(form)) return;

    var msgsId = form.getAttribute("data-messages-id");
    var thinkingId = form.getAttribute("data-thinking-id");
    var thinkingLabelId = form.getAttribute("data-thinking-label-id");
    var submitBtnId = form.getAttribute("data-submit-btn-id");

    var msgs = document.getElementById(msgsId);
    if (!msgs) return;

    // ユーザーメッセージ即時表示
    var ta = form.querySelector("textarea");
    var userText = ta ? ta.value.trim() : "";
    if (userText) {
      var u = document.createElement("div");
      u.className = "flex justify-end";
      u.innerHTML =
        '<div class="max-w-[85%] min-w-0 overflow-hidden">' +
        '<div class="rounded-xl px-3 sm:px-4 py-2 text-sm leading-relaxed break-words overflow-hidden bg-blue-600 text-white">' +
        userText.replace(/</g, "&lt;").replace(/\n/g, "<br>") +
        "</div></div>";
      msgs.appendChild(u);
      ta.value = "";
      ta.style.height = "auto";
    }

    // 思考中スピナー
    var t = document.createElement("div");
    t.id = thinkingId;
    t.className = "flex justify-start";
    t.innerHTML =
      '<div class="bg-gray-100 rounded-2xl px-4 py-2.5 text-sm text-gray-500">' +
      '<div class="flex items-center gap-2">' +
      '<span class="inline-block w-3.5 h-3.5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></span>' +
      '<span id="' +
      thinkingLabelId +
      '">思考中...</span>' +
      "</div></div>";
    msgs.appendChild(t);
    msgs.scrollTop = 9999;

    // 3秒後に「Web検索中」に切り替え
    form._searchTimer = setTimeout(function () {
      var label = document.getElementById(thinkingLabelId);
      if (!label) return;
      label.closest(".bg-gray-100").innerHTML =
        '<div class="flex items-center gap-2">' +
        '<svg class="w-3.5 h-3.5 animate-spin text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>' +
        "</svg>" +
        '<span class="text-blue-600">Web検索中...</span>' +
        "</div>" +
        '<div class="mt-1 flex gap-1">' +
        '<span class="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style="animation-delay:0ms"></span>' +
        '<span class="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style="animation-delay:150ms"></span>' +
        '<span class="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style="animation-delay:300ms"></span>' +
        "</div>";
    }, 3000);

    // ボタン無効化
    var btn = document.getElementById(submitBtnId);
    if (btn) {
      btn.disabled = true;
      btn.classList.add("opacity-40", "cursor-not-allowed");
      btn.classList.remove("hover:bg-blue-700");
    }
  });

  document.body.addEventListener("htmx:afterRequest", function (evt) {
    var form = evt.detail.elt;
    if (!isChatForm(form)) return;

    var thinkingId = form.getAttribute("data-thinking-id");
    var submitBtnId = form.getAttribute("data-submit-btn-id");
    var msgsId = form.getAttribute("data-messages-id");

    if (form._searchTimer) {
      clearTimeout(form._searchTimer);
      form._searchTimer = null;
    }

    var t = document.getElementById(thinkingId);
    if (t) t.remove();

    form.reset();
    var ta = form.querySelector("textarea");
    if (ta) ta.style.height = "auto";

    var btn = document.getElementById(submitBtnId);
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("opacity-40", "cursor-not-allowed");
      btn.classList.add("hover:bg-blue-700");
    }

    var msgs = document.getElementById(msgsId);
    if (msgs) msgs.scrollTop = 9999;
  });
})();
