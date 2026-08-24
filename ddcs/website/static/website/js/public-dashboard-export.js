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

  function figureMetaFrom(el) {
    if (!el) {
      return { title: "", caption: "" };
    }
    return {
      title: el.getAttribute("data-export-title") || "",
      caption: el.getAttribute("data-export-caption") || "",
    };
  }

  function loadImage(url) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        resolve(img);
      };
      img.onerror = function () {
        reject(new Error("Failed to load export image"));
      };
      img.src = url;
    });
  }

  function wrapLines(ctx, text, maxWidth) {
    var paragraphs = String(text || "").split(/\n/);
    var lines = [];
    paragraphs.forEach(function (para) {
      var words = para.trim().split(/\s+/).filter(Boolean);
      if (!words.length) {
        return;
      }
      var line = "";
      words.forEach(function (word) {
        var test = line ? line + " " + word : word;
        if (ctx.measureText(test).width > maxWidth && line) {
          lines.push(line);
          line = word;
        } else {
          line = test;
        }
      });
      if (line) {
        lines.push(line);
      }
    });
    return lines;
  }

  function fontsReady() {
    if (document.fonts && document.fonts.ready) {
      return document.fonts.ready.catch(function () {
        return undefined;
      });
    }
    return Promise.resolve();
  }

  function composeLabeledFigure(plotUrl, title, caption) {
    if (!title && !caption) {
      return Promise.resolve(plotUrl);
    }
    return fontsReady().then(function () {
      return loadImage(plotUrl);
    }).then(function (img) {
      var scale = DPI_SCALE;
      var pad = Math.round(32 * scale);
      var titleSize = Math.round(22 * scale);
      var captionSize = Math.round(13 * scale);
      var titleLh = Math.round(28 * scale);
      var captionLh = Math.round(16 * scale);
      var gap = Math.round(16 * scale);
      var plotW = img.width;
      var plotH = img.height;
      var textWidth = plotW;
      var fontStack = "Rubik, Arial, sans-serif";

      var canvas = document.createElement("canvas");
      var ctx = canvas.getContext("2d");
      ctx.font = "600 " + titleSize + "px " + fontStack;
      var titleLines = title ? wrapLines(ctx, title, textWidth) : [];
      ctx.font = "400 " + captionSize + "px " + fontStack;
      var captionLines = caption ? wrapLines(ctx, caption, textWidth) : [];

      var titleBlock = titleLines.length ? titleLines.length * titleLh + gap : 0;
      var captionBlock = captionLines.length
        ? gap + captionLines.length * captionLh
        : 0;
      canvas.width = plotW + pad * 2;
      canvas.height = pad + titleBlock + plotH + captionBlock + pad;

      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      var y = pad;
      if (titleLines.length) {
        ctx.fillStyle = "#111111";
        ctx.font = "600 " + titleSize + "px " + fontStack;
        ctx.textBaseline = "top";
        titleLines.forEach(function (line) {
          ctx.fillText(line, pad, y);
          y += titleLh;
        });
        y += gap;
      }
      ctx.drawImage(img, pad, y);
      y += plotH;
      if (captionLines.length) {
        y += gap;
        ctx.fillStyle = "#444444";
        ctx.font = "400 " + captionSize + "px " + fontStack;
        ctx.textBaseline = "top";
        captionLines.forEach(function (line) {
          if (line) {
            ctx.fillText(line, pad, y);
          }
          y += captionLh;
        });
      }
      return canvas.toDataURL("image/png");
    });
  }

  function setBusy(btn, busy) {
    btn.disabled = !!busy;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function exportPlotly(gd, filename, btn) {
    if (!window.Plotly || !gd) {
      return Promise.reject(new Error("Plotly graph not found"));
    }
    var meta = figureMetaFrom(btn);
    setBusy(btn, true);
    return window.Plotly.toImage(gd, {
      format: "png",
      width: Math.max(gd.clientWidth, 1),
      height: Math.max(gd.clientHeight, 1),
      scale: DPI_SCALE,
    })
      .then(function (url) {
        return composeLabeledFigure(url, meta.title, meta.caption);
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
    var meta = figureMetaFrom(el);
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
        return composeLabeledFigure(dataUrl, meta.title, meta.caption);
      })
      .then(function (dataUrl) {
        downloadDataUrl(dataUrl, filename);
      })
      .finally(function () {
        setBusy(btn, false);
      });
  }

  function filenameFor(btn) {
    var base = btn && btn.getAttribute("data-export-filename");
    if (!base) {
      var title = btn && btn.closest(".public-dashboard__plot, .public-dashboard__tierzeichen");
      var heading = title && title.querySelector("h2, h3");
      base = slugify(heading ? heading.textContent : "figure");
    }
    return base + "-300dpi.png";
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (window.__ddcsPublicPlotExportBound) {
      return;
    }
    window.__ddcsPublicPlotExportBound = true;

    document.querySelectorAll(".js-export-plotly-png").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var scope = btn.closest(
          ".carousel-item, .public-dashboard__plot, .public-plot-export"
        );
        var gd = scope && scope.querySelector(".js-plotly-plot, .plotly-graph-div");
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
        var filename = filenameFor(active || btn);
        exportDomElement(active, filename, btn).catch(function (err) {
          console.error(err);
        });
      });
    });
  });
})();
