"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("mt-form");
  const grid = document.getElementById("mt-grid");
  const fallback = document.getElementById("mt-fallback");
  if (!form || !grid || !fallback) return;
  const left = document.getElementById("mt-left");
  const right = document.getElementById("mt-right");
  const submit = document.getElementById("mt-check");
  const hint = document.getElementById("mt-hint");
  const selected = {left: null, right: null};
  grid.hidden = false;
  fallback.hidden = true;
  hint.hidden = false;
  submit.disabled = true;

  for (const button of grid.querySelectorAll("button[data-side]")) {
    button.addEventListener("click", () => {
      const side = button.dataset.side;
      for (const peer of grid.querySelectorAll(`button[data-side="${side}"]`)) {
        peer.setAttribute("aria-pressed", "false");
      }
      button.setAttribute("aria-pressed", "true");
      selected[side] = button.dataset.key;
      (side === "left" ? left : right).value = button.dataset.key;
      submit.disabled = !selected.left || !selected.right;
      hint.textContent = selected.left && selected.right
        ? "Пару вибрано. Натисни «Перевірити пару»."
        : (selected.left ? "Тепер вибери відповідник праворуч." : "Обери елемент ліворуч.");
    });
  }
  form.addEventListener("submit", () => { submit.disabled = true; });
});
