(function () {
  var copyButtons = document.querySelectorAll("[data-copy]");

  if (copyButtons.length > 0 && navigator.clipboard && navigator.clipboard.writeText) {
    copyButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        var value = button.getAttribute("data-copy");
        if (!value) {
          return;
        }

        navigator.clipboard.writeText(value).then(function () {
          var originalText = button.textContent;
          button.textContent = "Copied";
          window.setTimeout(function () {
            button.textContent = originalText;
          }, 1200);
        });
      });
    });
  } else {
    copyButtons.forEach(function (button) {
      button.setAttribute("disabled", "disabled");
      button.setAttribute("title", "Clipboard API unavailable");
    });
  }

  var year = document.getElementById("year");
  if (year) {
    year.textContent = String(new Date().getFullYear());
  }

  if (window.location.hash) {
    var target = document.querySelector(window.location.hash);
    if (target) {
      target.setAttribute("tabindex", "-1");
      target.focus();
    }
  }
})();
