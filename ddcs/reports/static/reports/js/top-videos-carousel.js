(function () {
  function yesNo(value) {
    return value === "Ja" || value === "true" || value === "1" ? "Ja" : "Nein";
  }

  function updateMeta(carousel, slide) {
    const meta = carousel.querySelector("#topVideoMeta");
    if (!meta || !slide) {
      return;
    }

    const setText = function (key, value) {
      const target = meta.querySelector(`[data-meta="${key}"]`);
      if (target) {
        target.textContent = value ?? "";
      }
    };

    setText("username", slide.dataset.username || "");
    setText("description", slide.dataset.description || "");
    setText("view-count", slide.dataset.viewCount || "0");
    setText("total-views", slide.dataset.totalViews || "—");
    setText("avg-watch", slide.dataset.avgWatch || "—");
    setText("liked", yesNo(slide.dataset.liked));
    setText("shared", yesNo(slide.dataset.shared));
    setText("saved", yesNo(slide.dataset.saved));
    setText("followed", yesNo(slide.dataset.followed));
  }

  function loadSlideIntoIframe(slide, iframe) {
    const embedSrc = slide?.dataset?.embedSrc;
    if (!slide || !iframe || !embedSrc) {
      return;
    }

    const title = slide.dataset.videoTitle;
    if (title) {
      iframe.title = title;
    }

    if (iframe.dataset.currentEmbedSrc === embedSrc) {
      return;
    }

    iframe.src = embedSrc;
    iframe.dataset.currentEmbedSrc = embedSrc;
  }

  function showActiveSlide(carousel, slide) {
    const iframe = carousel.querySelector("#topVideoEmbed");
    const targetSlide =
      slide || carousel.querySelector(".carousel-item.active");
    loadSlideIntoIframe(targetSlide, iframe);
    updateMeta(carousel, targetSlide);
  }

  function bindTopVideosCarousel(carousel) {
    if (!carousel || carousel.dataset.topVideosBound === "true") {
      return;
    }

    const refreshActiveSlide = function (slide) {
      window.setTimeout(function () {
        showActiveSlide(carousel, slide);
      }, 50);
    };

    carousel.addEventListener("slid.bs.carousel", function (event) {
      refreshActiveSlide(event.relatedTarget);
    });

    carousel.addEventListener("shown.bs.carousel", function (event) {
      refreshActiveSlide(event.relatedTarget);
    });

    carousel.addEventListener("click", function (event) {
      const trigger = event.target.closest(
        "[data-bs-slide-to], [data-bs-slide]",
      );
      if (!trigger) {
        return;
      }
      refreshActiveSlide();
    });

    carousel.dataset.topVideosBound = "true";
    showActiveSlide(carousel);
  }

  window.initTopVideosCarousel = function (root) {
    const carousel =
      root?.id === "topVideosCarousel"
        ? root
        : root?.querySelector?.("#topVideosCarousel") ||
          document.getElementById("topVideosCarousel");
    bindTopVideosCarousel(carousel);
  };

  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (
      event.detail.target?.id === "report-statistics" ||
      event.detail.target?.querySelector?.("#topVideosCarousel")
    ) {
      window.initTopVideosCarousel(event.detail.target);
    }
  });

  window.initTopVideosCarousel();
})();
