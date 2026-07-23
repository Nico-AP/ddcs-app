(function () {
  let preservedSlideIndex = 0;
  let preservedScrollY = 0;

  function findBehaviourCarousel(root) {
    const scope = root || document;
    if (scope.id === "behaviourProfileCarousel") {
      return scope;
    }
    return (
      scope.querySelector?.("#behaviourProfileCarousel") ||
      document.getElementById("behaviourProfileCarousel")
    );
  }

  function isVisible(element) {
    return Boolean(element && element.offsetParent !== null);
  }

  function isMobileViewport() {
    return window.matchMedia("(max-width: 767.98px)").matches;
  }

  function behaviourChartHeight(layoutHeight) {
    const desktopDefault = 112;
    const mobileDefault = 96;
    const resolved =
      typeof layoutHeight === "number" && layoutHeight > 0
        ? layoutHeight
        : desktopDefault;
    if (!isMobileViewport()) {
      return resolved;
    }
    return Math.round(resolved * (mobileDefault / desktopDefault));
  }

  function initDeferredPlot(script) {
    const targetId = script.dataset.target;
    const mount = targetId ? document.getElementById(targetId) : null;
    if (!mount || mount.dataset.plotlyReady === "true") {
      return Promise.resolve();
    }
    if (!isVisible(mount)) {
      return Promise.resolve();
    }
    if (typeof Plotly === "undefined") {
      return Promise.resolve();
    }

    let spec;
    try {
      spec = JSON.parse(script.textContent);
    } catch (_error) {
      return Promise.resolve();
    }

    const height = behaviourChartHeight(spec.layout?.height);
    spec.layout = spec.layout || {};
    spec.layout.height = height;
    spec.layout.autosize = true;
    mount.style.height = `${height}px`;

    return Plotly.newPlot(
      mount,
      spec.data,
      spec.layout,
      spec.config || {},
    ).then(function () {
      mount.dataset.plotlyReady = "true";
    });
  }

  function initDeferredBehaviourPlots(root, options) {
    const opts = options || {};
    const onlyVisible = opts.onlyVisible !== false;
    const carousel = findBehaviourCarousel(root);
    if (!carousel) {
      return Promise.resolve();
    }

    const scripts = Array.from(
      carousel.querySelectorAll("script.behaviour-plot-spec"),
    ).filter(function (script) {
      if (!onlyVisible) {
        return true;
      }
      const mount = document.getElementById(script.dataset.target || "");
      return isVisible(mount);
    });

    return Promise.all(
      scripts.map(function (script) {
        return initDeferredPlot(script);
      }),
    );
  }

  function scheduleDeferredPlotInit(root, options) {
    const opts = options || {};
    requestAnimationFrame(function () {
      initDeferredBehaviourPlots(root, opts);
      requestAnimationFrame(function () {
        initDeferredBehaviourPlots(root, opts);
      });
    });
  }

  function containsBehaviourCarousel(target) {
    return Boolean(
      target &&
        (target.id === "behaviourProfileCarousel" ||
          target.querySelector?.("#behaviourProfileCarousel")),
    );
  }

  function handleBehaviourChartsUpdate(target, options) {
    scheduleDeferredPlotInit(target, options);
    // Report HTMX swap uses a 1.5s transition plus settle time.
    window.setTimeout(function () {
      scheduleDeferredPlotInit(target, options);
    }, 1600);
    window.setTimeout(function () {
      scheduleDeferredPlotInit(target, options);
    }, 3200);
  }

  function isTypeSlideActive(carousel) {
    const activeItem = carousel.querySelector(".carousel-item.active");
    return Boolean(activeItem?.dataset?.behaviourTypeSlide === "true");
  }

  function syncBehaviourDetailChrome(carousel) {
    const root =
      document.getElementById("behaviour-profile-updates")?.parentElement ||
      document;
    const chromeNodes = root.querySelectorAll("[data-behaviour-detail-chrome]");
    if (!chromeNodes.length) {
      return;
    }

    const hide = Boolean(carousel && isTypeSlideActive(carousel));
    chromeNodes.forEach(function (node) {
      if (hide) {
        node.setAttribute("hidden", "");
      } else {
        node.removeAttribute("hidden");
      }
    });
  }

  function getActiveSlideIndex(carousel) {
    const activeItem = carousel.querySelector(".carousel-item.active");
    const items = carousel.querySelectorAll(".carousel-item");
    const index = Array.from(items).indexOf(activeItem);
    return index < 0 ? 0 : index;
  }

  function restoreCarouselSlide() {
    const carouselEl = document.getElementById("behaviourProfileCarousel");
    if (!carouselEl || typeof bootstrap === "undefined") {
      return;
    }

    const items = carouselEl.querySelectorAll(".carousel-item");
    if (!items.length) {
      return;
    }

    const index = Math.min(preservedSlideIndex, items.length - 1);
    const carousel = bootstrap.Carousel.getOrCreateInstance(carouselEl, {
      ride: false,
      interval: false,
    });
    carousel.to(index);
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    const form = event.detail.elt?.closest?.(
      ".behaviour-comparison-filters__form",
    );
    if (!form) {
      return;
    }

    preservedScrollY = window.scrollY;

    const carousel = document.getElementById("behaviourProfileCarousel");
    if (!carousel) {
      preservedSlideIndex = 0;
      return;
    }

    preservedSlideIndex = getActiveSlideIndex(carousel);
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    const target = event.detail.target;
    if (!target) {
      return;
    }

    // Filter updates swap without the long report transition — init immediately.
    if (target.id === "behaviour-profile-updates") {
      scheduleDeferredPlotInit(target);
    }
  });

  document.body.addEventListener("htmx:afterSettle", function (event) {
    const target = event.detail.target;
    if (!target) {
      return;
    }

    if (target.id === "behaviour-profile-updates") {
      restoreCarouselSlide();
      window.scrollTo({ top: preservedScrollY, left: 0, behavior: "instant" });
      handleBehaviourChartsUpdate(target);
      syncBehaviourDetailChrome(findBehaviourCarousel(target));
      return;
    }

    if (target.id === "report-statistics" || containsBehaviourCarousel(target)) {
      handleBehaviourChartsUpdate(target);
      syncBehaviourDetailChrome(findBehaviourCarousel(target));
    }
  });

  document.body.addEventListener("slid.bs.carousel", function (event) {
    if (event.target?.id !== "behaviourProfileCarousel") {
      return;
    }

    syncBehaviourDetailChrome(event.target);
    scheduleDeferredPlotInit(event.target, { onlyVisible: true });
    window.setTimeout(function () {
      initDeferredBehaviourPlots(event.target, { onlyVisible: true });
    }, 50);
  });

  document.addEventListener("DOMContentLoaded", function () {
    syncBehaviourDetailChrome(findBehaviourCarousel(document));
  });
})();
