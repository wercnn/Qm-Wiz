// Phone-first page with three tabs: Brief, Cards, Weeks.
// Asks the server every 2 seconds and redraws when something changed.
const $ = (id) => document.getElementById(id);

let view = "brief";       // which tab is open
let shown = null;         // lecture picked by the user, or null for the next one
let historyModule = null; // module picked in "All weeks", or null to follow the shown lecture
let cards = [];
let cardIndex = 0;
let flipped = false;
let cardsFor = null;      // which brief the cards belong to
let slidesFor = null;     // lecture id whose PDF the cards point into
let slideOpen = false;
let slideShown = null;
let jumpFilled = false;
let lastDrawn = "";
let moduleCodes = [];

// One colour per module: [main, pale]. Modules get them in alphabetical order of their codes.
const COLOURS = [
  ["#534ab7", "#eeedfe"], ["#0f6e56", "#e1f5ee"], ["#c2491f", "#faece7"], ["#185fa5", "#e6f1fb"],
  ["#b03a68", "#fbeaf0"], ["#9a5f0b", "#faeeda"], ["#3b6d11", "#eaf3de"],
];
const colour = (module) => COLOURS[Math.max(0, moduleCodes.indexOf(module)) % COLOURS.length];

const fmtDay = (iso) => new Date(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/London" });
const fmtTime = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });
const STATUS = { ready: "Brief ready", preparing: "Reading slides", waiting: "Waiting for slides" };

function fill(el, items, make) {
  el.replaceChildren(...items.map(make));
}

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function tinted(el, module) {
  // Give an element its module's colours as --c and --c-tint.
  const [main, pale] = colour(module);
  el.style.setProperty("--c", main);
  el.style.setProperty("--c-tint", pale);
  return el;
}

function openView(name) {
  view = name;
  for (const id of ["brief", "cards", "weeks"]) $(`view-${id}`).hidden = id !== name;
  for (const tab of document.querySelectorAll(".tabs button")) tab.classList.toggle("on", tab.dataset.view === name);
  document.body.dataset.view = name; // the lecture header is smaller outside the brief
  window.scrollTo(0, 0);
}

function show(id) {
  // Show another lecture and go to its brief.
  shown = id;
  historyModule = null;
  lastDrawn = "";
  openView("brief");
  refresh();
}

function drawCard(turn) {
  const card = cards[cardIndex];
  const el = $("card");
  el.className = flipped ? "card answer" : "card";
  if (turn) {
    void el.offsetWidth; // restart the animation
    el.classList.add("turn");
  }
  el.replaceChildren(
    document.createTextNode(flipped ? card.answer : card.question),
    node("small", flipped ? `From slide ${card.slide}` : "Tap to see the answer"),
  );
  fill($("progress"), cards, (_, i) => node("i", undefined, i <= cardIndex ? "done" : ""));
  $("show-slide").textContent = slideOpen ? "Hide slide" : `Show slide ${card.slide}`;
  drawSlide();
}

function moveCard(step) {
  cardIndex = (cardIndex + step + cards.length) % cards.length;
  flipped = false;
  drawCard();
}

function drawSlide() {
  // The PDF page the current card came from, shown under the card.
  const box = $("slide");
  box.hidden = !slideOpen;
  const wanted = slideOpen ? `${slidesFor}#${cards[cardIndex].slide}` : null;
  if (wanted === slideShown) return; // flipping a card must not reload the picture
  slideShown = wanted;
  if (!slideOpen) { box.replaceChildren(); return; }
  const page = cards[cardIndex].slide;
  const picture = document.createElement("img");
  picture.alt = `Slide ${page}`;
  picture.src = `/api/slides/${slidesFor}/${page}.png`;
  const link = node("a", "Open the full slide deck");
  link.href = `/api/slides/${slidesFor}#page=${page}`;
  link.target = "_blank";
  box.replaceChildren(picture, link);
}

function drawLecture(lec, in24h) {
  const box = $("lecture");
  if (!lec) {
    box.replaceChildren(node("h1", "No more lectures in the timetable."));
    $("brief").hidden = true;
    return;
  }
  const [main, pale] = colour(lec.module);
  document.documentElement.style.setProperty("--m", main);
  document.documentElement.style.setProperty("--m-tint", pale);

  const parts = [];
  if (shown) {
    const back = node("button", "← Next lecture", "back");
    back.onclick = () => show(null);
    parts.push(back);
  }
  const label = lec.past ? "Past lecture" : in24h ? "Next lecture, today" : shown ? "Upcoming" : "Next lecture";
  const facts = node("div", undefined, "facts");
  facts.append(
    node("span", STATUS[lec.status], `state ${lec.status}`),
    node("span", lec.room),
    node("span", `Week ${lec.week}`),
  );
  parts.push(
    node("div", `${label} · ${fmtDay(lec.start)}, ${fmtTime(lec.start)} to ${fmtTime(lec.end)}`, "when"),
    node("h1", lec.prep ? lec.prep.topic : lec.title),
    node("div", `${lec.module} ${lec.title}`, "module"),
    facts,
  );
  box.replaceChildren(...parts);

  // Brief tab
  $("brief").hidden = !lec.prep;
  $("waiting").hidden = Boolean(lec.prep);
  $("deck").hidden = !lec.prep;
  $("no-cards").hidden = Boolean(lec.prep);
  if (!lec.prep) {
    const title = node("strong", lec.status === "preparing" ? "Reading the slides" : "Waiting for slides");
    $("waiting").replaceChildren(title, document.createTextNode("Nothing to do. The brief appears here when the slides are out."));
    cardsFor = null;
    return;
  }

  const prep = lec.prep;
  $("overview").textContent = prep.overview;
  fill($("covers"), prep.covers, (text) => node("li", text));
  fill($("questions"), prep.questions, (text) => node("li", text));
  $("link").textContent = prep.link_to_last_week;
  fill($("terms"), prep.key_terms, (t) => {
    const pair = node("div");
    pair.append(node("dt", t.term), node("dd", t.definition));
    return pair;
  });

  // Cards tab
  const key = lec.id + prep.pdf_sha256;
  if (cardsFor !== key) {
    cardsFor = key;
    cards = prep.cards;
    slidesFor = lec.id;
    slideOpen = false;
    cardIndex = 0;
    flipped = false;
    drawCard();
  }
}

function lectureRow(lec, data, badge, name, sub) {
  const li = tinted(node("li"), lec.module);
  if (data.next && lec.id === data.next.id) li.className = "shown";
  const text = node("div", undefined, "text");
  text.append(node("div", name, "name"), node("div", sub, "sub"));
  li.append(node("span", badge, "num"), text, node("span", undefined, `mark ${lec.status}`));
  li.onclick = () => show(lec.id);
  return li;
}

function drawWeeks(data) {
  // Next 7 days: the day of the week in the badge.
  fill($("upcoming"), data.upcoming, (lec) => lectureRow(
    lec, data,
    new Date(lec.start).toLocaleDateString("en-GB", { weekday: "short", timeZone: "Europe/London" }),
    lec.topic || lec.title,
    `${lec.module} · ${fmtTime(lec.start)} · ${lec.room}`,
  ));

  // All weeks: every lecture that has a brief, one module at a time.
  const withBriefs = [...new Set(data.history.map((lec) => lec.module))].sort();
  const current = historyModule || (data.next && withBriefs.includes(data.next.module) ? data.next.module : withBriefs[0]);
  fill($("history-modules"), withBriefs, (code) => {
    const pill = tinted(node("button", data.modules[code], code === current ? "on" : ""), code);
    pill.type = "button";
    pill.onclick = () => { historyModule = code; lastDrawn = ""; refresh(); };
    return pill;
  });
  const rows = data.history.filter((lec) => lec.module === current);
  if (rows.length === 0) {
    $("history").replaceChildren(node("li", "Nothing yet. Briefs stay here after each lecture.", "none"));
  } else {
    fill($("history"), rows, (lec) => lectureRow(
      lec, data, String(lec.week), lec.topic, fmtDay(lec.start) + (lec.past ? "" : " · upcoming"),
    ));
  }

  fill($("activity"), [...data.activity].reverse(), (item) => node("li", `${item.time}  ${item.text}`));
}

function fillJump(upcoming) {
  // One option per lecture: 8am that day.
  if (jumpFilled) return;
  jumpFilled = true;
  for (const lec of upcoming) {
    const option = node("option", `8am, ${fmtDay(lec.start)} (${lec.module})`);
    option.value = lec.start.slice(0, 10) + "T08:00:00";
    $("jump").append(option);
  }
}

async function refresh() {
  let data;
  try {
    const response = await fetch("/api/today" + (shown ? `?show=${encodeURIComponent(shown)}` : ""));
    data = await response.json();
  } catch {
    return; // server restarting; try again next time
  }
  $("clock").textContent = `${fmtDay(data.now)}, ${fmtTime(data.now)}` + (data.demo_clock ? " (demo clock)" : "");

  // Redraw only when something changed, so taps and scrolling are not interrupted.
  const snapshot = JSON.stringify({ ...data, now: null });
  if (snapshot === lastDrawn) return;
  lastDrawn = snapshot;

  moduleCodes = Object.keys(data.modules).sort();
  $("notice").hidden = !data.notice;
  $("notice").textContent = data.notice || "";
  drawLecture(data.next, data.next && data.next_24h.includes(data.next.id));
  fillJump(data.upcoming);
  drawWeeks(data);
}

for (const tab of document.querySelectorAll(".tabs button")) tab.onclick = () => openView(tab.dataset.view);

$("card").onclick = () => { flipped = !flipped; drawCard(true); };
$("show-slide").onclick = () => { slideOpen = !slideOpen; drawCard(); };
$("next").onclick = () => moveCard(1);
$("prev").onclick = () => moveCard(-1);

// Keyboard: arrow keys move between cards, space flips.
document.addEventListener("keydown", (event) => {
  if (!cards.length || $("deck").hidden || ["SELECT", "INPUT"].includes(event.target.tagName)) return;
  if (event.key === "ArrowRight") moveCard(1);
  else if (event.key === "ArrowLeft") moveCard(-1);
  else if (event.key === " " && event.target.tagName !== "BUTTON") { event.preventDefault(); flipped = !flipped; drawCard(true); }
});

// Swipe the card left or right to move between cards.
let touchX = null;
$("card").addEventListener("touchstart", (event) => { touchX = event.touches[0].clientX; }, { passive: true });
$("card").addEventListener("touchend", (event) => {
  if (touchX === null) return;
  const moved = event.changedTouches[0].clientX - touchX;
  touchX = null;
  if (Math.abs(moved) < 50) return; // a tap, handled by onclick
  event.preventDefault();           // do not also flip the card
  moveCard(moved < 0 ? 1 : -1);
});

$("jump").onchange = async (event) => {
  await fetch("/api/clock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ at: event.target.value || null }),
  });
  shown = null;
  lastDrawn = "";
  refresh();
};

refresh();
setInterval(refresh, 2000);
