// Populates the homepage "Recent research" grid from data/articles.json
(function () {
  "use strict";
  var grid = document.getElementById("home-research-grid");
  if (!grid) return;

  fetch("data/articles.json")
    .then(function (res) { return res.json(); })
    .then(function (articles) {
      articles
        .slice()
        .sort(function (a, b) { return new Date(b.date) - new Date(a.date); })
        .slice(0, 3)
        .forEach(function (a) {
          var card = document.createElement("a");
          card.href = a.url;
          card.className = "article-card";
          card.innerHTML =
            '<div class="article-meta">' + formatDate(a.date) + "</div>" +
            "<h3>" + a.title + "</h3>" +
            '<p class="deck">' + a.deck + "</p>" +
            '<div class="article-tags">' + a.tags.map(function (t) { return '<span class="tag">' + t + "</span>"; }).join("") + "</div>" +
            '<span class="article-read">Read the piece <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 8h10M9 4l4 4-4 4"/></svg></span>';
          grid.appendChild(card);
        });
    })
    .catch(function (err) { console.error(err); });

  function formatDate(iso) {
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  }
})();
