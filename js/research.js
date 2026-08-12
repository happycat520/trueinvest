// CrystalWell — Research listing page
(function () {
  "use strict";
  var grid = document.getElementById("research-grid");
  var filterBar = document.getElementById("filter-bar");
  if (!grid) return;

  var ARTICLES = [];
  var activeTag = "all";

  function formatDate(iso) {
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  }

  function cardHTML(a) {
    return (
      '<a class="article-card" href="' + a.url + '">' +
      '<div class="article-meta">' + formatDate(a.date) + "</div>" +
      "<h3>" + a.title + "</h3>" +
      '<p class="deck">' + a.deck + "</p>" +
      '<div class="article-tags">' + a.tags.map(function (t) { return '<span class="tag">' + t + "</span>"; }).join("") + "</div>" +
      '<span class="article-read">Read the piece <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 8h10M9 4l4 4-4 4"/></svg></span>' +
      "</a>"
    );
  }

  function render() {
    var list = activeTag === "all" ? ARTICLES : ARTICLES.filter(function (a) { return a.tags.indexOf(activeTag) !== -1; });
    if (!list.length) {
      grid.innerHTML = '<p class="dash-empty" style="grid-column:1/-1;">No articles match this filter yet.</p>';
      return;
    }
    grid.innerHTML = list
      .slice()
      .sort(function (a, b) { return new Date(b.date) - new Date(a.date); })
      .map(cardHTML)
      .join("");
  }

  function buildFilters() {
    var tags = [];
    ARTICLES.forEach(function (a) {
      a.tags.forEach(function (t) { if (tags.indexOf(t) === -1) tags.push(t); });
    });
    tags.forEach(function (t) {
      var btn = document.createElement("button");
      btn.className = "filter-chip";
      btn.dataset.tag = t;
      btn.textContent = t;
      filterBar.appendChild(btn);
    });
    filterBar.addEventListener("click", function (e) {
      var btn = e.target.closest(".filter-chip");
      if (!btn) return;
      filterBar.querySelectorAll(".filter-chip").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      activeTag = btn.dataset.tag;
      render();
    });
  }

  fetch("data/articles.json")
    .then(function (res) { return res.json(); })
    .then(function (articles) {
      ARTICLES = articles;
      buildFilters();
      render();
    })
    .catch(function (err) {
      console.error(err);
      grid.innerHTML = '<p class="dash-empty" style="grid-column:1/-1;">Couldn\'t load articles right now.</p>';
    });
})();
