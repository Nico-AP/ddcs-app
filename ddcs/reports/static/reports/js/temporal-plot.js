(function () {
  const MOBILE_MQ = window.matchMedia("(max-width: 767.98px)");
  const DESKTOP_HEIGHT = 400;
  const MOBILE_HEIGHT = 312;

  function isMobile() {
    return MOBILE_MQ.matches;
  }

  function layoutForViewport() {
    if (isMobile()) {
      return {
        height: MOBILE_HEIGHT,
        "yaxis.showticklabels": false,
        "margin.l": 0,
      };
    }
    return {
      height: DESKTOP_HEIGHT,
      "yaxis.showticklabels": true,
      "margin.l": 0,
    };
  }

  function findTemporalPlots(root) {
    const scope = root || document;
    return scope.querySelectorAll(
      ".temporal-plot .plotly-graph-div, .temporal-plot .js-plotly-plot",
    );
  }

  function applyTemporalPlotLayout(root) {
    if (typeof Plotly === "undefined") {
      return;
    }

    findTemporalPlots(root).forEach(function (plotEl) {
      if (!plotEl.querySelector(".main-svg")) {
        return;
      }
      try {
        Plotly.relayout(plotEl, layoutForViewport());
      } catch (_error) {
        // Plotly may not have finished initialising yet.
      }
    });
  }

  function scheduleApply(root) {
    requestAnimationFrame(function () {
      applyTemporalPlotLayout(root);
      window.setTimeout(function () {
        applyTemporalPlotLayout(root);
      }, 100);
      window.setTimeout(function () {
        applyTemporalPlotLayout(root);
      }, 400);
      window.setTimeout(function () {
        applyTemporalPlotLayout(root);
      }, 1800);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    scheduleApply();
  });

  MOBILE_MQ.addEventListener("change", function () {
    scheduleApply();
  });

  window.addEventListener("resize", function () {
    scheduleApply();
  });

  document.body.addEventListener("shown.bs.carousel", function (event) {
    if (event.target?.classList?.contains("public-plot-carousel")) {
      scheduleApply(event.target);
    }
  });

  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (event.detail.target?.id === "report-statistics") {
      scheduleApply(event.detail.target);
    }
  });
})();
