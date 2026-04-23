window.PlotlyConfig = {MathJaxConfig: 'local'};

// Party Likes Barplot
window.PLOTLYENV = window.PLOTLYENV || {};
if (document.getElementById("50d9012b-a93a-46e1-8e6f-a530f24492dd")) {
  Plotly.newPlot("50d9012b-a93a-46e1-8e6f-a530f24492dd", [{
    "hovertemplate": "\u003cb\u003e%{y}\u003c\u002fb\u003e\u003cbr\u003eLikes insgesamt: %{x:,.0f}\u003cbr\u003e\u003cextra\u003e\u003c\u002fextra\u003e",
    "marker": {
      "color": ["rgba(159,159,159,0.9)", "rgba(142,89,115,0.9)", "rgba(69,69,69,0.9)", "rgba(248,235,69,0.9)", "rgba(118,174,99,0.9)", "rgba(228,69,79,0.9)", "rgba(69,180,226,0.9)", "rgba(202,102,151,0.9)"],
      "line": {"width": 0}
    },
    "orientation": "h",
    "showlegend": false,
    "width": 0.6,
    "x": [1097027, 1734185, 2912787, 3430479, 4838972, 10774375, 12195846, 14301388],
    "y": ["Sonstige", "BSW", "CDU\u002fCSU", "FDP", "Gr\u00fcne", "SPD", "AfD", "Linke"],
    "type": "bar",
    "xaxis": "x",
    "yaxis": "y"
  }, {
    "hovertemplate": "\u003cb\u003e%{y}\u003c\u002fb\u003e\u003cbr\u003eLikes pro Video: %{x:,.0f}\u003cbr\u003e\u003cextra\u003e\u003c\u002fextra\u003e",
    "marker": {
      "color": ["rgba(159,159,159,0.9)", "rgba(69,69,69,0.9)", "rgba(118,174,99,0.9)", "rgba(248,235,69,0.9)", "rgba(69,180,226,0.9)", "rgba(228,69,79,0.9)", "rgba(142,89,115,0.9)", "rgba(202,102,151,0.9)"],
      "line": {"width": 0}
    },
    "orientation": "h",
    "showlegend": false,
    "width": 0.6,
    "x": [1103.6488933601609, 1393.0114777618364, 1870.4955546965598, 2846.870539419087, 3046.6764926305273, 3065.2560455192033, 5453.411949685535, 14201.974180734856],
    "y": ["Sonstige", "CDU\u002fCSU", "Gr\u00fcne", "FDP", "AfD", "SPD", "BSW", "Linke"],
    "type": "bar",
    "xaxis": "x2",
    "yaxis": "y2"
  }], {
    "template": {
      "data": {
        "histogram2dcontour": [{
          "type": "histogram2dcontour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "choropleth": [{"type": "choropleth", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "histogram2d": [{
          "type": "histogram2d",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "heatmap": [{
          "type": "heatmap",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "contourcarpet": [{"type": "contourcarpet", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "contour": [{
          "type": "contour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "surface": [{
          "type": "surface",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "mesh3d": [{"type": "mesh3d", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "scatter": [{"fillpattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}, "type": "scatter"}],
        "parcoords": [{"type": "parcoords", "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolargl": [{"type": "scatterpolargl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "bar": [{
          "error_x": {"color": "#2a3f5f"},
          "error_y": {"color": "#2a3f5f"},
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          },
          "type": "bar"
        }],
        "scattergeo": [{"type": "scattergeo", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolar": [{"type": "scatterpolar", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "histogram": [{
          "marker": {"pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}},
          "type": "histogram"
        }],
        "scattergl": [{"type": "scattergl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatter3d": [{
          "type": "scatter3d",
          "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
          "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}
        }],
        "scattermap": [{"type": "scattermap", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattermapbox": [{"type": "scattermapbox", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterternary": [{"type": "scatterternary", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattercarpet": [{"type": "scattercarpet", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "carpet": [{
          "aaxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "baxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "type": "carpet"
        }],
        "table": [{
          "cells": {"fill": {"color": "#EBF0F8"}, "line": {"color": "white"}},
          "header": {"fill": {"color": "#C8D4E3"}, "line": {"color": "white"}},
          "type": "table"
        }],
        "barpolar": [{
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          }, "type": "barpolar"
        }],
        "pie": [{"automargin": true, "type": "pie"}]
      }, "layout": {
        "autotypenumbers": "strict",
        "colorway": ["#636efa", "#EF553B", "#00cc96", "#ab63fa", "#FFA15A", "#19d3f3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"],
        "font": {"color": "#2a3f5f"},
        "hovermode": "closest",
        "hoverlabel": {"align": "left"},
        "paper_bgcolor": "white",
        "plot_bgcolor": "#E5ECF6",
        "polar": {
          "bgcolor": "#E5ECF6",
          "angularaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "radialaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "ternary": {
          "bgcolor": "#E5ECF6",
          "aaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "baxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "caxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "coloraxis": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
        "colorscale": {
          "sequential": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "sequentialminus": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "diverging": [[0, "#8e0152"], [0.1, "#c51b7d"], [0.2, "#de77ae"], [0.3, "#f1b6da"], [0.4, "#fde0ef"], [0.5, "#f7f7f7"], [0.6, "#e6f5d0"], [0.7, "#b8e186"], [0.8, "#7fbc41"], [0.9, "#4d9221"], [1, "#276419"]]
        },
        "xaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "yaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "scene": {
          "xaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "yaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "zaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          }
        },
        "shapedefaults": {"line": {"color": "#2a3f5f"}},
        "annotationdefaults": {"arrowcolor": "#2a3f5f", "arrowhead": 0, "arrowwidth": 1},
        "geo": {
          "bgcolor": "white",
          "landcolor": "#E5ECF6",
          "subunitcolor": "white",
          "showland": true,
          "showlakes": true,
          "lakecolor": "white"
        },
        "title": {"x": 0.05},
        "mapbox": {"style": "light"}
      }
    },
    "xaxis": {
      "anchor": "y",
      "domain": [0.0, 1.0],
      "title": {"font": {"size": 20, "color": "white"}, "text": ""},
      "tickfont": {"size": 20, "color": "white"},
      "showticklabels": true,
      "showgrid": true,
      "gridwidth": 1,
      "gridcolor": "gray",
      "zeroline": true,
      "zerolinecolor": "gray",
      "zerolinewidth": 1
    },
    "yaxis": {
      "anchor": "x",
      "domain": [0.6000000000000001, 1.0],
      "tickfont": {"size": 20, "color": "white"},
      "tickangle": 0,
      "showgrid": false,
      "ticksuffix": "  ",
      "zeroline": false,
      "mirror": false,
      "showline": false,
      "linecolor": "rgba(0,0,0,0)"
    },
    "xaxis2": {
      "anchor": "y2",
      "domain": [0.0, 1.0],
      "title": {"font": {"size": 20, "color": "white"}, "text": "Anzahl"},
      "tickfont": {"size": 20, "color": "white"},
      "showticklabels": true,
      "showgrid": true,
      "gridwidth": 1,
      "gridcolor": "gray",
      "zeroline": true,
      "zerolinecolor": "gray",
      "zerolinewidth": 1
    },
    "yaxis2": {
      "anchor": "x2",
      "domain": [0.0, 0.4],
      "tickfont": {"size": 20, "color": "white"},
      "tickangle": 0,
      "showgrid": false,
      "ticksuffix": "  ",
      "zeroline": false,
      "mirror": false,
      "showline": false,
      "linecolor": "rgba(0,0,0,0)"
    },
    "annotations": [{
      "font": {"size": 22, "weight": 500, "family": "Rubik, sans-serif", "color": "white"},
      "showarrow": false,
      "text": "Likes insgesamt",
      "x": 0.5,
      "xanchor": "center",
      "xref": "paper",
      "y": 1.0,
      "yanchor": "bottom",
      "yref": "paper"
    }, {
      "font": {"size": 22, "weight": 500, "family": "Rubik, sans-serif", "color": "white"},
      "showarrow": false,
      "text": "Likes pro Video",
      "x": 0.5,
      "xanchor": "center",
      "xref": "paper",
      "y": 0.4,
      "yanchor": "bottom",
      "yref": "paper"
    }],
    "title": {"font": {"size": 20, "color": "white"}},
    "font": {"size": 25, "color": "white", "family": "Rubik, Arial, sans-serif"},
    "margin": {"r": 0, "t": 50, "l": 0, "b": 0},
    "dragmode": false,
    "height": 450,
    "plot_bgcolor": "#313131",
    "paper_bgcolor": "#313131"
  }, {
    "responsive": true,
    "displayModeBar": false,
    "staticPlot": false,
    "scrollZoom": false,
    "doubleClick": false,
    "showAxisDragHandles": false,
    "showAxisRangeEntryBoxes": false,
    "modeBarButtonsToRemove": ["zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"]
  })
}

// Party squares plot
window.PLOTLYENV = window.PLOTLYENV || {};
if (document.getElementById("63ddd742-0798-435b-9772-8c3d2d02958f")) {
  Plotly.newPlot("63ddd742-0798-435b-9772-8c3d2d02958f", [{
    "hovertemplate": "\u003cb\u003e%{label}\u003c\u002fb\u003e\u003cbr\u003eVideos: %{value}\u003cextra\u003e\u003c\u002fextra\u003e",
    "labels": ["AfD", "SPD", "Gr\u00fcne", "CDU\u002fCSU", "FDP", "Linke", "Sonstige", "BSW"],
    "marker": {
      "colors": ["rgba(69,180,226,0.9)", "rgba(228,69,79,0.9)", "rgba(118,174,99,0.9)", "rgba(69,69,69,0.9)", "rgba(248,235,69,0.9)", "rgba(202,102,151,0.9)", "rgba(159,159,159,0.9)", "rgba(142,89,115,0.9)"],
      "line": {"color": "white", "width": 0}
    },
    "parents": ["", "", "", "", "", "", "", ""],
    "textfont": {"color": "white", "family": "Rubik, Arial, sans-serif", "size": 28},
    "textinfo": "label+value",
    "values": [4003, 3515, 2587, 2091, 1205, 1007, 994, 318],
    "type": "treemap"
  }], {
    "template": {
      "data": {
        "histogram2dcontour": [{
          "type": "histogram2dcontour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "choropleth": [{"type": "choropleth", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "histogram2d": [{
          "type": "histogram2d",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "heatmap": [{
          "type": "heatmap",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "contourcarpet": [{"type": "contourcarpet", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "contour": [{
          "type": "contour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "surface": [{
          "type": "surface",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "mesh3d": [{"type": "mesh3d", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "scatter": [{"fillpattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}, "type": "scatter"}],
        "parcoords": [{"type": "parcoords", "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolargl": [{"type": "scatterpolargl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "bar": [{
          "error_x": {"color": "#2a3f5f"},
          "error_y": {"color": "#2a3f5f"},
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          },
          "type": "bar"
        }],
        "scattergeo": [{"type": "scattergeo", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolar": [{"type": "scatterpolar", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "histogram": [{
          "marker": {"pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}},
          "type": "histogram"
        }],
        "scattergl": [{"type": "scattergl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatter3d": [{
          "type": "scatter3d",
          "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
          "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}
        }],
        "scattermap": [{"type": "scattermap", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattermapbox": [{"type": "scattermapbox", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterternary": [{"type": "scatterternary", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattercarpet": [{"type": "scattercarpet", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "carpet": [{
          "aaxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "baxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "type": "carpet"
        }],
        "table": [{
          "cells": {"fill": {"color": "#EBF0F8"}, "line": {"color": "white"}},
          "header": {"fill": {"color": "#C8D4E3"}, "line": {"color": "white"}},
          "type": "table"
        }],
        "barpolar": [{
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          }, "type": "barpolar"
        }],
        "pie": [{"automargin": true, "type": "pie"}]
      }, "layout": {
        "autotypenumbers": "strict",
        "colorway": ["#636efa", "#EF553B", "#00cc96", "#ab63fa", "#FFA15A", "#19d3f3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"],
        "font": {"color": "#2a3f5f"},
        "hovermode": "closest",
        "hoverlabel": {"align": "left"},
        "paper_bgcolor": "white",
        "plot_bgcolor": "#E5ECF6",
        "polar": {
          "bgcolor": "#E5ECF6",
          "angularaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "radialaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "ternary": {
          "bgcolor": "#E5ECF6",
          "aaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "baxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "caxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "coloraxis": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
        "colorscale": {
          "sequential": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "sequentialminus": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "diverging": [[0, "#8e0152"], [0.1, "#c51b7d"], [0.2, "#de77ae"], [0.3, "#f1b6da"], [0.4, "#fde0ef"], [0.5, "#f7f7f7"], [0.6, "#e6f5d0"], [0.7, "#b8e186"], [0.8, "#7fbc41"], [0.9, "#4d9221"], [1, "#276419"]]
        },
        "xaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "yaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "scene": {
          "xaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "yaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "zaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          }
        },
        "shapedefaults": {"line": {"color": "#2a3f5f"}},
        "annotationdefaults": {"arrowcolor": "#2a3f5f", "arrowhead": 0, "arrowwidth": 1},
        "geo": {
          "bgcolor": "white",
          "landcolor": "#E5ECF6",
          "subunitcolor": "white",
          "showland": true,
          "showlakes": true,
          "lakecolor": "white"
        },
        "title": {"x": 0.05},
        "mapbox": {"style": "light"}
      }
    },
    "margin": {"t": 0, "l": 0, "r": 0, "b": 0},
    "font": {"size": 25, "color": "white", "family": "Rubik, Arial, sans-serif"},
    "dragmode": false,
    "paper_bgcolor": "#313131",
    "plot_bgcolor": "#313131",
    "height": 450
  }, {"responsive": true, "displayModeBar": false, "staticPlot": true})
}

// Party timeseries plot
window.PLOTLYENV = window.PLOTLYENV || {};
if (document.getElementById("8bec9d85-25c7-4d71-99e8-d737a6661239")) {
  Plotly.newPlot("8bec9d85-25c7-4d71-99e8-d737a6661239", [{
    "fillcolor": "rgba(159,159,159,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "Sonstige",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "Sonstige",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "CQcJCAUOCg4LDwMLCwwOEA0HBw0REg8QCw0SFRYSDxAVFhENFR0SERgXHhUiExAYHRogIy0TDgwGBws="},
    "type": "scatter"
  }, {
    "fillcolor": "rgba(142,89,115,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "BSW",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "BSW",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "AQEAAgIDAgYIBAQDBQUIBAYEBQIIBQUEAgQFBgUDBgUJBgUCBAgEBAgLCQYKBQUKCg4NDA0HAgQAAgI="},
    "type": "scatter"
  }, {
    "fillcolor": "rgba(202,102,151,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "Linke",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "Linke",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "BAQEBAcFDAgMDgoIDA4QEBMTCxgOEg4UFAsRDhcbFQ4MFxgYFBUSDhEWHxEcExcaGRobIRskDgoMCgw="},
    "type": "scatter"
  }, {
    "fillcolor": "rgba(69,180,226,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "AfD",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "AfD",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {
      "dtype": "i2",
      "bdata": "HgAVACUAGgAjACwANAA\u002fADIAMABWADYALQBAAEAAQgBAACcAIQA8ADsASQBQADoARAA\u002fAEgASwBrAE8AhAA6ADQARgBMADoAUAA\u002fADsALQBAAF0AWgByAFoATAA\u002fAFcAXQBvAGQAawB5AF0ANwBCADMAOgA\u002fAA=="
    },
    "type": "scatter"
  }, {
    "fillcolor": "rgba(248,235,69,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "FDP",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "FDP",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "BQcMBggRGA8ZEA0LDhMUFBQNCBMYExoYCw4NDSQaGhASGhUYIBUMEhssISkcGw8fIiksJiQXBwULBQM="},
    "type": "scatter"
  }, {
    "fillcolor": "rgba(118,174,99,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "Gr\u00fcne",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "Gr\u00fcne",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "BxUXCAYYIxorLRsXMDAoKTYdFCUwLikqGho1NUdEQSEbMTE4MTsYHDVAMzxIKSdCSUdOZFQlFSMmLSk="},
    "type": "scatter"
  }, {
    "fillcolor": "rgba(69,69,69,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "CDU\u002fCSU",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "CDU\u002fCSU",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "EQsRDRATIRQTFRQcISUfGiIgGiMdIyUeHRcxJDkxLhgPMSYyKSwhNTU4Ny40HigtL0k8QEYeGhAZGBg="},
    "type": "scatter"
  }, {
    "fillcolor": "rgba(228,69,79,0.9)",
    "hoverlabel": {"bgcolor": "white", "font": {"color": "white", "family": "Rubik, sans-serif", "size": 16}},
    "hovertemplate": "%{y} Videos\u003cextra\u003e\u003c\u002fextra\u003e",
    "legendgroup": "SPD",
    "line": {"smoothing": 1.3, "width": 0},
    "mode": "lines",
    "name": "SPD",
    "showlegend": true,
    "stackgroup": "one",
    "x": ["2025-01-01T00:00:00.000000000", "2025-01-02T00:00:00.000000000", "2025-01-03T00:00:00.000000000", "2025-01-04T00:00:00.000000000", "2025-01-05T00:00:00.000000000", "2025-01-06T00:00:00.000000000", "2025-01-07T00:00:00.000000000", "2025-01-08T00:00:00.000000000", "2025-01-09T00:00:00.000000000", "2025-01-10T00:00:00.000000000", "2025-01-11T00:00:00.000000000", "2025-01-12T00:00:00.000000000", "2025-01-13T00:00:00.000000000", "2025-01-14T00:00:00.000000000", "2025-01-15T00:00:00.000000000", "2025-01-16T00:00:00.000000000", "2025-01-17T00:00:00.000000000", "2025-01-18T00:00:00.000000000", "2025-01-19T00:00:00.000000000", "2025-01-20T00:00:00.000000000", "2025-01-21T00:00:00.000000000", "2025-01-22T00:00:00.000000000", "2025-01-23T00:00:00.000000000", "2025-01-24T00:00:00.000000000", "2025-01-25T00:00:00.000000000", "2025-01-26T00:00:00.000000000", "2025-01-27T00:00:00.000000000", "2025-01-28T00:00:00.000000000", "2025-01-29T00:00:00.000000000", "2025-01-30T00:00:00.000000000", "2025-01-31T00:00:00.000000000", "2025-02-01T00:00:00.000000000", "2025-02-02T00:00:00.000000000", "2025-02-03T00:00:00.000000000", "2025-02-04T00:00:00.000000000", "2025-02-05T00:00:00.000000000", "2025-02-06T00:00:00.000000000", "2025-02-07T00:00:00.000000000", "2025-02-08T00:00:00.000000000", "2025-02-09T00:00:00.000000000", "2025-02-10T00:00:00.000000000", "2025-02-11T00:00:00.000000000", "2025-02-12T00:00:00.000000000", "2025-02-13T00:00:00.000000000", "2025-02-14T00:00:00.000000000", "2025-02-15T00:00:00.000000000", "2025-02-16T00:00:00.000000000", "2025-02-17T00:00:00.000000000", "2025-02-18T00:00:00.000000000", "2025-02-19T00:00:00.000000000", "2025-02-20T00:00:00.000000000", "2025-02-21T00:00:00.000000000", "2025-02-22T00:00:00.000000000", "2025-02-23T00:00:00.000000000", "2025-02-24T00:00:00.000000000", "2025-02-25T00:00:00.000000000", "2025-02-26T00:00:00.000000000", "2025-02-27T00:00:00.000000000", "2025-02-28T00:00:00.000000000"],
    "y": {"dtype": "i1", "bdata": "EBMWERUkJSo2PzIoLjY1Rj8oIzZBPTAyIh46RHRfUDAwPj1CTkcqP1ZfXzxaPEVOb2xpdW9HHSUoKyI="},
    "type": "scatter"
  }], {
    "template": {
      "data": {
        "histogram2dcontour": [{
          "type": "histogram2dcontour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "choropleth": [{"type": "choropleth", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "histogram2d": [{
          "type": "histogram2d",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "heatmap": [{
          "type": "heatmap",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "contourcarpet": [{"type": "contourcarpet", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "contour": [{
          "type": "contour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "surface": [{
          "type": "surface",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "mesh3d": [{"type": "mesh3d", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "scatter": [{"fillpattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}, "type": "scatter"}],
        "parcoords": [{"type": "parcoords", "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolargl": [{"type": "scatterpolargl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "bar": [{
          "error_x": {"color": "#2a3f5f"},
          "error_y": {"color": "#2a3f5f"},
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          },
          "type": "bar"
        }],
        "scattergeo": [{"type": "scattergeo", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolar": [{"type": "scatterpolar", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "histogram": [{
          "marker": {"pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}},
          "type": "histogram"
        }],
        "scattergl": [{"type": "scattergl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatter3d": [{
          "type": "scatter3d",
          "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
          "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}
        }],
        "scattermap": [{"type": "scattermap", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattermapbox": [{"type": "scattermapbox", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterternary": [{"type": "scatterternary", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattercarpet": [{"type": "scattercarpet", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "carpet": [{
          "aaxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "baxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "type": "carpet"
        }],
        "table": [{
          "cells": {"fill": {"color": "#EBF0F8"}, "line": {"color": "white"}},
          "header": {"fill": {"color": "#C8D4E3"}, "line": {"color": "white"}},
          "type": "table"
        }],
        "barpolar": [{
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          }, "type": "barpolar"
        }],
        "pie": [{"automargin": true, "type": "pie"}]
      }, "layout": {
        "autotypenumbers": "strict",
        "colorway": ["#636efa", "#EF553B", "#00cc96", "#ab63fa", "#FFA15A", "#19d3f3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"],
        "font": {"color": "#2a3f5f"},
        "hovermode": "closest",
        "hoverlabel": {"align": "left"},
        "paper_bgcolor": "white",
        "plot_bgcolor": "#E5ECF6",
        "polar": {
          "bgcolor": "#E5ECF6",
          "angularaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "radialaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "ternary": {
          "bgcolor": "#E5ECF6",
          "aaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "baxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "caxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "coloraxis": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
        "colorscale": {
          "sequential": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "sequentialminus": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "diverging": [[0, "#8e0152"], [0.1, "#c51b7d"], [0.2, "#de77ae"], [0.3, "#f1b6da"], [0.4, "#fde0ef"], [0.5, "#f7f7f7"], [0.6, "#e6f5d0"], [0.7, "#b8e186"], [0.8, "#7fbc41"], [0.9, "#4d9221"], [1, "#276419"]]
        },
        "xaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "yaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "scene": {
          "xaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "yaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "zaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          }
        },
        "shapedefaults": {"line": {"color": "#2a3f5f"}},
        "annotationdefaults": {"arrowcolor": "#2a3f5f", "arrowhead": 0, "arrowwidth": 1},
        "geo": {
          "bgcolor": "white",
          "landcolor": "#E5ECF6",
          "subunitcolor": "white",
          "showland": true,
          "showlakes": true,
          "lakecolor": "white"
        },
        "title": {"x": 0.05},
        "mapbox": {"style": "light"}
      }
    },
    "legend": {
      "font": {"size": 14, "color": "white"},
      "orientation": "h",
      "yanchor": "bottom",
      "y": 1.02,
      "xanchor": "center",
      "x": 0.5
    },
    "font": {"size": 25, "color": "white"},
    "title": {"font": {"color": "white", "size": 1}, "pad": {"b": 0}, "text": "\u003cbr\u003e"},
    "margin": {"r": 0, "t": 0, "l": 0, "b": 0},
    "hoverlabel": {"namelength": 0},
    "xaxis": {
      "title": {"text": "Datum (2025)", "font": {"size": 18, "color": "white"}},
      "hoverformat": "%d.%m.%Y",
      "tickfont": {"size": 18, "color": "white"},
      "showgrid": true,
      "gridwidth": 1,
      "gridcolor": "gray",
      "zeroline": true,
      "zerolinewidth": 1,
      "zerolinecolor": "gray",
      "tickangle": 45,
      "tickformat": "%d.%m"
    },
    "yaxis": {
      "title": {"text": "Anzahl Videos (kumuliert)", "font": {"size": 18, "color": "white"}},
      "tickfont": {"size": 18, "color": "white"},
      "showgrid": true,
      "gridwidth": 1,
      "gridcolor": "gray",
      "zeroline": true,
      "zerolinewidth": 1,
      "zerolinecolor": "gray"
    },
    "dragmode": false,
    "showlegend": true,
    "autosize": true,
    "height": 400,
    "plot_bgcolor": "#313131",
    "paper_bgcolor": "#313131",
    "hovermode": "x unified",
    "hoverdistance": 100
  }, {
    "responsive": true,
    "displayModeBar": false,
    "staticPlot": false,
    "scrollZoom": false,
    "doubleClick": false,
    "showAxisDragHandles": false,
    "showAxisRangeEntryBoxes": false,
    "modeBarButtonsToRemove": ["zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"]
  })
}

// Party view barplot
window.PLOTLYENV = window.PLOTLYENV || {};
if (document.getElementById("fc76f5eb-a90e-454d-86d3-ddce5b3962d0")) {
  Plotly.newPlot("fc76f5eb-a90e-454d-86d3-ddce5b3962d0", [{
    "hovertemplate": "\u003cb\u003e%{y}\u003c\u002fb\u003e\u003cbr\u003eViews insgesamt: %{x:,.0f}\u003cbr\u003e\u003cextra\u003e\u003c\u002fextra\u003e",
    "marker": {
      "color": ["rgba(159,159,159,0.9)", "rgba(142,89,115,0.9)", "rgba(248,235,69,0.9)", "rgba(118,174,99,0.9)", "rgba(69,69,69,0.9)", "rgba(202,102,151,0.9)", "rgba(69,180,226,0.9)", "rgba(228,69,79,0.9)"],
      "line": {"width": 0}
    },
    "orientation": "h",
    "showlegend": false,
    "width": 0.6,
    "x": [14869585, 28287002, 73767496, 76408376, 85272927, 105056424, 143360342, 144735257],
    "y": ["Sonstige", "BSW", "FDP", "Gr\u00fcne", "CDU\u002fCSU", "Linke", "AfD", "SPD"],
    "type": "bar",
    "xaxis": "x",
    "yaxis": "y"
  }, {
    "hovertemplate": "\u003cb\u003e%{y}\u003c\u002fb\u003e\u003cbr\u003eViews pro Video: %{x:,.0f}\u003cbr\u003e\u003cextra\u003e\u003c\u002fextra\u003e",
    "marker": {
      "color": ["rgba(159,159,159,0.9)", "rgba(118,174,99,0.9)", "rgba(69,180,226,0.9)", "rgba(69,69,69,0.9)", "rgba(228,69,79,0.9)", "rgba(248,235,69,0.9)", "rgba(142,89,115,0.9)", "rgba(202,102,151,0.9)"],
      "line": {"width": 0}
    },
    "orientation": "h",
    "showlegend": false,
    "width": 0.6,
    "x": [14959.341046277666, 29535.514495554697, 35813.22558081439, 40780.93113342898, 41176.4600284495, 61217.83900414938, 88952.83647798742, 104326.14101290963],
    "y": ["Sonstige", "Gr\u00fcne", "AfD", "CDU\u002fCSU", "SPD", "FDP", "BSW", "Linke"],
    "type": "bar",
    "xaxis": "x2",
    "yaxis": "y2"
  }], {
    "template": {
      "data": {
        "histogram2dcontour": [{
          "type": "histogram2dcontour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "choropleth": [{"type": "choropleth", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "histogram2d": [{
          "type": "histogram2d",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "heatmap": [{
          "type": "heatmap",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "contourcarpet": [{"type": "contourcarpet", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "contour": [{
          "type": "contour",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "surface": [{
          "type": "surface",
          "colorbar": {"outlinewidth": 0, "ticks": ""},
          "colorscale": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]]
        }],
        "mesh3d": [{"type": "mesh3d", "colorbar": {"outlinewidth": 0, "ticks": ""}}],
        "scatter": [{"fillpattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}, "type": "scatter"}],
        "parcoords": [{"type": "parcoords", "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolargl": [{"type": "scatterpolargl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "bar": [{
          "error_x": {"color": "#2a3f5f"},
          "error_y": {"color": "#2a3f5f"},
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          },
          "type": "bar"
        }],
        "scattergeo": [{"type": "scattergeo", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterpolar": [{"type": "scatterpolar", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "histogram": [{
          "marker": {"pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}},
          "type": "histogram"
        }],
        "scattergl": [{"type": "scattergl", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatter3d": [{
          "type": "scatter3d",
          "line": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
          "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}
        }],
        "scattermap": [{"type": "scattermap", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattermapbox": [{"type": "scattermapbox", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scatterternary": [{"type": "scatterternary", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "scattercarpet": [{"type": "scattercarpet", "marker": {"colorbar": {"outlinewidth": 0, "ticks": ""}}}],
        "carpet": [{
          "aaxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "baxis": {
            "endlinecolor": "#2a3f5f",
            "gridcolor": "white",
            "linecolor": "white",
            "minorgridcolor": "white",
            "startlinecolor": "#2a3f5f"
          },
          "type": "carpet"
        }],
        "table": [{
          "cells": {"fill": {"color": "#EBF0F8"}, "line": {"color": "white"}},
          "header": {"fill": {"color": "#C8D4E3"}, "line": {"color": "white"}},
          "type": "table"
        }],
        "barpolar": [{
          "marker": {
            "line": {"color": "#E5ECF6", "width": 0.5},
            "pattern": {"fillmode": "overlay", "size": 10, "solidity": 0.2}
          }, "type": "barpolar"
        }],
        "pie": [{"automargin": true, "type": "pie"}]
      }, "layout": {
        "autotypenumbers": "strict",
        "colorway": ["#636efa", "#EF553B", "#00cc96", "#ab63fa", "#FFA15A", "#19d3f3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"],
        "font": {"color": "#2a3f5f"},
        "hovermode": "closest",
        "hoverlabel": {"align": "left"},
        "paper_bgcolor": "white",
        "plot_bgcolor": "#E5ECF6",
        "polar": {
          "bgcolor": "#E5ECF6",
          "angularaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "radialaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "ternary": {
          "bgcolor": "#E5ECF6",
          "aaxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "baxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""},
          "caxis": {"gridcolor": "white", "linecolor": "white", "ticks": ""}
        },
        "coloraxis": {"colorbar": {"outlinewidth": 0, "ticks": ""}},
        "colorscale": {
          "sequential": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "sequentialminus": [[0.0, "#0d0887"], [0.1111111111111111, "#46039f"], [0.2222222222222222, "#7201a8"], [0.3333333333333333, "#9c179e"], [0.4444444444444444, "#bd3786"], [0.5555555555555556, "#d8576b"], [0.6666666666666666, "#ed7953"], [0.7777777777777778, "#fb9f3a"], [0.8888888888888888, "#fdca26"], [1.0, "#f0f921"]],
          "diverging": [[0, "#8e0152"], [0.1, "#c51b7d"], [0.2, "#de77ae"], [0.3, "#f1b6da"], [0.4, "#fde0ef"], [0.5, "#f7f7f7"], [0.6, "#e6f5d0"], [0.7, "#b8e186"], [0.8, "#7fbc41"], [0.9, "#4d9221"], [1, "#276419"]]
        },
        "xaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "yaxis": {
          "gridcolor": "white",
          "linecolor": "white",
          "ticks": "",
          "title": {"standoff": 15},
          "zerolinecolor": "white",
          "automargin": true,
          "zerolinewidth": 2
        },
        "scene": {
          "xaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "yaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          },
          "zaxis": {
            "backgroundcolor": "#E5ECF6",
            "gridcolor": "white",
            "linecolor": "white",
            "showbackground": true,
            "ticks": "",
            "zerolinecolor": "white",
            "gridwidth": 2
          }
        },
        "shapedefaults": {"line": {"color": "#2a3f5f"}},
        "annotationdefaults": {"arrowcolor": "#2a3f5f", "arrowhead": 0, "arrowwidth": 1},
        "geo": {
          "bgcolor": "white",
          "landcolor": "#E5ECF6",
          "subunitcolor": "white",
          "showland": true,
          "showlakes": true,
          "lakecolor": "white"
        },
        "title": {"x": 0.05},
        "mapbox": {"style": "light"}
      }
    },
    "xaxis": {
      "anchor": "y",
      "domain": [0.0, 1.0],
      "title": {"font": {"size": 20, "color": "white"}, "text": ""},
      "tickfont": {"size": 20, "color": "white"},
      "showticklabels": true,
      "showgrid": true,
      "gridwidth": 1,
      "gridcolor": "gray",
      "zeroline": true,
      "zerolinecolor": "gray",
      "zerolinewidth": 1
    },
    "yaxis": {
      "anchor": "x",
      "domain": [0.6000000000000001, 1.0],
      "tickfont": {"size": 20, "color": "white"},
      "tickangle": 0,
      "showgrid": false,
      "ticksuffix": "  ",
      "zeroline": false,
      "mirror": false,
      "showline": false,
      "linecolor": "rgba(0,0,0,0)"
    },
    "xaxis2": {
      "anchor": "y2",
      "domain": [0.0, 1.0],
      "title": {"font": {"size": 20, "color": "white"}, "text": "Anzahl"},
      "tickfont": {"size": 20, "color": "white"},
      "showticklabels": true,
      "showgrid": true,
      "gridwidth": 1,
      "gridcolor": "gray",
      "zeroline": true,
      "zerolinecolor": "gray",
      "zerolinewidth": 1
    },
    "yaxis2": {
      "anchor": "x2",
      "domain": [0.0, 0.4],
      "tickfont": {"size": 20, "color": "white"},
      "tickangle": 0,
      "showgrid": false,
      "ticksuffix": "  ",
      "zeroline": false,
      "mirror": false,
      "showline": false,
      "linecolor": "rgba(0,0,0,0)"
    },
    "annotations": [{
      "font": {"size": 22, "weight": 500, "family": "Rubik, sans-serif", "color": "white"},
      "showarrow": false,
      "text": "Views insgesamt",
      "x": 0.5,
      "xanchor": "center",
      "xref": "paper",
      "y": 1.0,
      "yanchor": "bottom",
      "yref": "paper"
    }, {
      "font": {"size": 22, "weight": 500, "family": "Rubik, sans-serif", "color": "white"},
      "showarrow": false,
      "text": "Views pro Video",
      "x": 0.5,
      "xanchor": "center",
      "xref": "paper",
      "y": 0.4,
      "yanchor": "bottom",
      "yref": "paper"
    }],
    "title": {"font": {"size": 20, "color": "white"}},
    "font": {"size": 25, "color": "white", "family": "Rubik, Arial, sans-serif"},
    "margin": {"r": 0, "t": 50, "l": 0, "b": 0},
    "dragmode": false,
    "height": 450,
    "plot_bgcolor": "#313131",
    "paper_bgcolor": "#313131"
  }, {
    "responsive": true,
    "displayModeBar": false,
    "staticPlot": false,
    "scrollZoom": false,
    "doubleClick": false,
    "showAxisDragHandles": false,
    "showAxisRangeEntryBoxes": false,
    "modeBarButtonsToRemove": ["zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"]
  })
}
