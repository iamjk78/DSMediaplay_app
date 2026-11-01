/* The bar at the end of a page that switches between the two languages of the guide: once a language has been picked
   (a click on one of its links), the bar is not shown again, on this page or on any other. */
(function () {
    var KEY = "dsm-guide-language-picked";
    var bar = document.getElementById("language-bar");
    if (!bar) {
        return;
    }
    try {
        if (window.localStorage.getItem(KEY)) {
            bar.hidden = true;
            return;
        }
    } catch (error) {
        /* storage is not available: the bar simply stays */
    }
    bar.addEventListener("click", function (event) {
        var target = event.target;
        if (target && target.closest && target.closest("a")) {
            try {
                window.localStorage.setItem(KEY, "1");
            } catch (error) {
                /* the choice is not remembered, the bar comes back on the next page */
            }
            bar.hidden = true;
        }
    });
})();
