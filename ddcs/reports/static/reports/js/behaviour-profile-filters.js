(function () {
  let preservedSlideIndex = 0;
  let preservedScrollY = 0;

  function resizePlotlyCharts() {
    window.dispatchEvent(new Event("resize"));
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

  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (event.detail.target?.id !== "behaviour-profile-updates") {
      return;
    }

    restoreCarouselSlide();
    window.scrollTo({ top: preservedScrollY, left: 0, behavior: "instant" });
    resizePlotlyCharts();
  });

  document.body.addEventListener("shown.bs.carousel", function (event) {
    if (event.target?.id === "behaviourProfileCarousel") {
      resizePlotlyCharts();
    }
  });
})();
