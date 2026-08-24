/**
 * Export public-dashboard figures as PNG at ~300 dpi (scale = 300/96).
 */
(function () {
  "use strict";

  var DPI_SCALE = 300 / 96;

  function slugify(text) {
    return String(text || "figure")
      .toLowerCase()
      .replace(/ä/g, "ae")
      .replace(/ö/g, "oe")
      .replace(/ü/g, "ue")
      .replace(/ß/g, "ss")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
  }

  function downloadDataUrl(dataUrl, filename) {
    var a = document.createElement("a");
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function setBusy(btn, busy) {
    btn.disabled = !!busy;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function exportPlotly(gd, filename, btn) {
    if (!window.Plotly || !gd) {
      return Promise.reject(new Error("Plotly graph not found"));
    }
    setBusy(btn, true);
    return window.Plotly.toImage(gd, {
      format: "png",
      width: Math.max(gd.clientWidth, 1),
      height: Math.max(gd.clientHeight, 1),
      scale: DPI_SCALE,
    })
      .then(function (url) {
        downloadDataUrl(url, filename);
      })
      .finally(function () {
        setBusy(btn, false);
      });
  }

  function absolutizeUrls(root) {
    root.querySelectorAll("[src]").forEach(function (el) {
      var src = el.getAttribute("src");
      if (src) {
        el.setAttribute("src", new URL(src, window.location.href).href);
      }
    });
    root.querySelectorAll("[href]").forEach(function (el) {
      var href = el.getAttribute("href");
      if (href && href.charAt(0) === "/") {
        el.setAttribute("href", new URL(href, window.location.href).href);
      }
    });
  }

  function waitForImages(root) {
    var imgs = Array.prototype.slice.call(root.querySelectorAll("img"));
    if (!imgs.length) {
      return Promise.resolve();
    }
    return Promise.all(
      imgs.map(function (img) {
        if (img.complete) {
          return Promise.resolve();
        }
        return new Promise(function (resolve) {
          img.addEventListener("load", resolve, { once: true });
          img.addEventListener("error", resolve, { once: true });
        });
      })
    );
  }

  function copyComputedStyles(source, target) {
    var computed = window.getComputedStyle(source);
    var cssText = "";
    for (var i = 0; i < computed.length; i++) {
      var prop = computed[i];
      cssText += prop + ":" + computed.getPropertyValue(prop) + ";";
    }
    target.style.cssText = cssText;
    var sourceChildren = source.children;
    var targetChildren = target.children;
    for (var j = 0; j < sourceChildren.length; j++) {
      if (targetChildren[j]) {
        copyComputedStyles(sourceChildren[j], targetChildren[j]);
      }
    }
  }

  function exportDomElement(el, filename, btn) {
    if (!el) {
      return Promise.reject(new Error("Element not found"));
    }
    setBusy(btn, true);
    var width = Math.ceil(el.getBoundingClientRect().width);
    var height = Math.ceil(el.getBoundingClientRect().height);
    var clone = el.cloneNode(true);
    copyComputedStyles(el, clone);
    absolutizeUrls(clone);

    var wrapper = document.createElement("div");
    wrapper.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
    wrapper.style.cssText =
      "width:" +
      width +
      "px;height:" +
      height +
      "px;background:#fff;box-sizing:border-box;";
    wrapper.appendChild(clone);

    return waitForImages(wrapper)
      .then(function () {
        var serializer = new XMLSerializer();
        var xhtml = serializer.serializeToString(wrapper);
        var svg =
          '<svg xmlns="http://www.w3.org/2000/svg" width="' +
          width * DPI_SCALE +
          '" height="' +
          height * DPI_SCALE +
          '">' +
          '<foreignObject width="' +
          width +
          '" height="' +
          height +
          '" transform="scale(' +
          DPI_SCALE +
          ')">' +
          xhtml +
          "</foreignObject></svg>";

        var svgUrl =
          "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
        return new Promise(function (resolve, reject) {
          var img = new Image();
          img.onload = function () {
            var canvas = document.createElement("canvas");
            canvas.width = Math.round(width * DPI_SCALE);
            canvas.height = Math.round(height * DPI_SCALE);
            var ctx = canvas.getContext("2d");
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0);
            resolve(canvas.toDataURL("image/png"));
          };
          img.onerror = function () {
            reject(new Error("Failed to render chart image"));
          };
          img.src = svgUrl;
        });
      })
      .then(function (dataUrl) {
        downloadDataUrl(dataUrl, filename);
      })
      .finally(function () {
        setBusy(btn, false);
      });
  }

  function filenameFor(btn) {
    var base = btn.getAttribute("data-export-filename");
    if (!base) {
      var title = btn.closest(".public-dashboard__plot, .public-dashboard__tierzeichen");
      var heading = title && title.querySelector("h2, h3");
      base = slugify(heading ? heading.textContent : "figure");
    }
    return base + "-300dpi.png";
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-export-plotly-png").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var plot = btn.closest(".public-dashboard__plot");
        var gd = plot && plot.querySelector(".js-plotly-plot, .plotly-graph-div");
        exportPlotly(gd, filenameFor(btn), btn).catch(function (err) {
          console.error(err);
        });
      });
    });

    document.querySelectorAll(".js-export-tierzeichen-png").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var carousel = document.getElementById("tierzeichenCarousel");
        var active =
          carousel &&
          carousel.querySelector(".carousel-item.active .tierzeichen-chart");
        exportDomElement(active, filenameFor(btn), btn).catch(function (err) {
          console.error(err);
        });
      });
    });
  });
})();
