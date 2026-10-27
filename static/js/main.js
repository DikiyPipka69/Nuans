"use strict";

// ---------- Оттенки (меняют акцентный цвет сайта) ----------
const SHADES = [
  ["Малина", "#B83A62"],
  ["Слива", "#7A3B8C"],
  ["Вишня", "#9E2A3B"],
  ["Мокко", "#7B5446"],
];
const dotsBox = document.getElementById("dots");

function setShade(index) {
  document.documentElement.style.setProperty("--accent", SHADES[index][1]);
  document.getElementById("swatch-name").textContent = SHADES[index][0];
  [...dotsBox.children].forEach((btn, i) => {
    btn.setAttribute("aria-pressed", i === index ? "true" : "false");
  });
}

SHADES.forEach(([name, color], i) => {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dot";
  btn.style.background = color;
  btn.setAttribute("aria-label", name);
  btn.addEventListener("click", () => setShade(i));
  dotsBox.appendChild(btn);
});
setShade(0);

// ---------- Переключение страниц по адресу вида #/services ----------
const TITLES = {
  home: "Нюанс — студия красоты",
  services: "Услуги и цены — Нюанс",
  masters: "Мастера — Нюанс",
  contacts: "Запись и контакты — Нюанс",
  privacy: "Политика конфиденциальности — Нюанс",
};
const menu = document.getElementById("menu");
const burger = document.getElementById("burger");

function route() {
  let key = location.hash.replace(/^#\/?/, "") || "home";
  if (!TITLES[key]) key = "home";
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === "p-" + key));
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === key) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = TITLES[key];
  menu.classList.remove("open");
  burger.setAttribute("aria-expanded", "false");
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
route();

burger.addEventListener("click", () => {
  const open = menu.classList.toggle("open");
  burger.setAttribute("aria-expanded", String(open));
});

// ---------- Прайс из API ----------
function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;  // textContent, а не innerHTML: так безопаснее
  return node;
}
const rub = (n) => new Intl.NumberFormat("ru-RU").format(n) + " ₽";

async function loadServices() {
  const list = document.getElementById("services-list");
  const select = document.getElementById("f-service");
  try {
    const res = await fetch("/api/services");
    if (!res.ok) throw new Error("bad status");
    const groups = await res.json();
    list.replaceChildren();
    select.replaceChildren();
    for (const group of groups) {
      const ul = el("ul");
      ul.className = "price";
      for (const item of group.items) {
        const li = el("li");
        const name = el("span", item.name);
        name.appendChild(el("small", item.duration));
        li.append(name, el("b", rub(item.price)));
        ul.appendChild(li);
        select.appendChild(new Option(item.name, item.name));
      }
      list.append(el("h2", group.group), ul);
    }
  } catch {
    list.textContent = "Не удалось загрузить прайс. Обновите страницу.";
  }
}
loadServices();

// ---------- Форма записи -> POST /api/lead ----------
const form = document.getElementById("lead-form");
const errorBox = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-btn");

// Одноразовый токен формы: без него сервер заявку не принимает (защита от ботов).
// Берём его сразу при загрузке страницы, а после любой неудачной отправки берём новый.
let formToken = "";
async function refreshToken() {
  try {
    const res = await fetch("/api/form-token");
    if (res.ok) formToken = (await res.json()).token;
  } catch {
    formToken = "";
  }
}
refreshToken();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = document.getElementById("f-name").value.trim();
  const phone = document.getElementById("f-phone").value;
  const service = document.getElementById("f-service").value;
  const consent = document.getElementById("f-consent").checked;
  const website = document.getElementById("f-website").value;

  if (name.length < 2) { errorBox.textContent = "Введите имя."; return; }
  if (phone.replace(/\D/g, "").length < 10) { errorBox.textContent = "Введите телефон полностью, не меньше 10 цифр."; return; }
  if (!service) { errorBox.textContent = "Прайс ещё не загрузился, подождите секунду."; return; }
  if (!consent) { errorBox.textContent = "Поставьте галочку согласия, иначе заявку отправить нельзя."; return; }

  if (!formToken) await refreshToken();
  errorBox.textContent = "";
  submitBtn.disabled = true;
  submitBtn.setAttribute("aria-busy", "true");
  submitBtn.textContent = "Отправляем…";
  try {
    const res = await fetch("/api/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, phone, service, consent, website, token: formToken }),
    });
    if (res.ok) {
      form.hidden = true;
      document.getElementById("form-ok").hidden = false;
      return;
    }
    formToken = "";  // токен одноразовый
    if (res.status === 429) {
      errorBox.textContent = "Слишком много запросов. Подождите минуту и попробуйте снова.";
    } else if (res.status === 400) {
      errorBox.textContent = "Форма устарела или отправлена слишком быстро. Подождите секунду и нажмите «Отправить» ещё раз.";
    } else {
      errorBox.textContent = "Проверьте введённые данные.";
    }
    refreshToken();
  } catch {
    errorBox.textContent = "Нет связи с сервером. Попробуйте ещё раз.";
    formToken = "";
    refreshToken();
  } finally {
    submitBtn.disabled = false;
    submitBtn.removeAttribute("aria-busy");
    submitBtn.textContent = "Отправить заявку";
  }
});
