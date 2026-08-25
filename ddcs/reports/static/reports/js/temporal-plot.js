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
        // On small screens the horizontal legend eats vertical space;
        // party names remain available via the unified hover/tap tooltip.
        showlegend: false,
      };
    }
    return {
      height: DESKTOP_HEIGHT,
      "yaxis.showticklabels": true,
      "margin.l": 0,
      showlegend: true,
    };
  }

  function compactLegendLayout() {
    return { showlegend: !isMobile() };
  }

  function findTemporalPlots(root) {
    const scope = root || document;
    return scope.querySelectorAll(
      ".temporal-plot:not(.temporal-plot--compact) .plotly-graph-div, .temporal-plot:not(.temporal-plot--compact) .js-plotly-plot",
    );
  }

  function findCompactTemporalPlots(root) {
    const scope = root || document;
    return scope.querySelectorAll(
      ".temporal-plot--compact .plotly-graph-div, .temporal-plot--compact .js-plotly-plot",
    );
  }

  function findAllTemporalPlotEls(root) {
    const scope = root || document;
    return scope.querySelectorAll(
      ".temporal-plot .plotly-graph-div, .temporal-plot .js-plotly-plot",
    );
  }

  function clearTemporalHovers() {
    if (typeof Plotly === "undefined" || !Plotly.Fx) {
      return;
    }
    findAllTemporalPlotEls().forEach(function (plotEl) {
      try {
        Plotly.Fx.unhover(plotEl);
      } catch (_error) {
        // Plot not ready / already cleared.
      }
    });
  }

  function resizeCompactPlots(root) {
    if (typeof Plotly === "undefined") {
      return;
    }
    findCompactTemporalPlots(root).forEach(function (plotEl) {
      try {
        Plotly.Plots.resize(plotEl);
        Plotly.relayout(plotEl, compactLegendLayout());
      } catch (_error) {
        // Plotly may not have finished initialising yet.
      }
    });
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
        Plotly.Plots.resize(plotEl);
        Plotly.relayout(plotEl, layoutForViewport());
      } catch (_error) {
        // Plotly may not have finished initialising yet.
      }
    });
  }

  function scheduleApply(root) {
    requestAnimationFrame(function () {
      applyTemporalPlotLayout(root);
      resizeCompactPlots(root);
      window.setTimeout(function () {
        applyTemporalPlotLayout(root);
        resizeCompactPlots(root);
      }, 100);
      window.setTimeout(function () {
        applyTemporalPlotLayout(root);
        resizeCompactPlots(root);
      }, 400);
      window.setTimeout(function () {
        applyTemporalPlotLayout(root);
        resizeCompactPlots(root);
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

  function onPublicPlotCarouselEvent(event) {
    if (event.target?.classList?.contains("public-plot-carousel")) {
      scheduleApply(event.target);
    }
  }

  document.body.addEventListener("shown.bs.carousel", onPublicPlotCarouselEvent);
  document.body.addEventListener("slid.bs.carousel", onPublicPlotCarouselEvent);

  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (event.detail.target?.id === "report-statistics") {
      scheduleApply(event.detail.target);
    }
  });

  // Sticky mobile hover: dismiss when tapping outside the chart.
  document.addEventListener(
    "pointerdown",
    function (event) {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      if (
        target.closest(
          ".temporal-plot .js-plotly-plot, .temporal-plot .plotly-graph-div",
        )
      ) {
        return;
      }
      clearTemporalHovers();
    },
    true,
  );
})();
