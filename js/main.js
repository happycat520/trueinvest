// CrystalWell Analytics — shared site behavior
(function () {
  "use strict";

  // Mobile nav toggle
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    links.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  // Scroll reveal
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealEls.length) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  }

  // Daily Digest + contact forms — submit to Formspree, same endpoint as
  // crystalwell-site (tehochess/crystalwell-site), so both sites' submissions
  // land in the same inbox.
  function wireForm(form, successText) {
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();

      // Belt-and-suspenders: required/type="email" should already stop an
      // empty or malformed address before this handler ever runs, but some
      // mobile browsers/in-app webviews/autofill tools don't always enforce
      // that reliably. Explicitly check and let the browser show its own
      // specific message ("Please fill out this field", "Please include an
      // '@'...") rather than falling through to a generic network-error
      // message that doesn't tell the person what's actually wrong.
      if (!form.checkValidity()) {
        form.reportValidity();
        return;
      }

      var note = form.querySelector(".form-note");
      var button = form.querySelector('button[type="submit"]');
      var originalText = button ? button.textContent : null;

      if (button) {
        button.disabled = true;
        button.textContent = "Sending...";
      }
      if (note) {
        note.textContent = "";
        note.classList.remove("visible");
      }

      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
      })
        .then(function (response) {
          if (note) {
            note.textContent = response.ok
              ? successText
              : "Something went wrong. Please try again in a moment.";
            note.classList.add("visible");
          }
          if (response.ok) form.reset();
        })
        .catch(function () {
          if (note) {
            note.textContent = "Something went wrong. Please try again in a moment.";
            note.classList.add("visible");
          }
        })
        .finally(function () {
          if (button) {
            button.disabled = false;
            button.textContent = originalText;
          }
        });
    });
  }

  wireForm(document.querySelector("#digest-form"), "Thanks — you're subscribed.");
  wireForm(document.querySelector("#contact-form"), "Message received — we'll get back to you shortly.");
})();
