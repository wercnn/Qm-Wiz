// Today page. Asks the server every 2 seconds and redraws.
const $ = (id) => document.getElementById(id);

let shown = null;      // lecture picked from the list, or null for the next one
let cards = [];
let cardIndex = 0;
let flipped = false;
let cardsFor = null;   // which brief the cards belong to
let slidesFor = null;  // lecture id whose PDF the cards point into
let slideOpen = false;
let slideShown = null;
let jumpFilled = false;
let lastDrawn = "";

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

function drawCard() {
  const card = cards[cardIndex];
  const el = $("card");
  el.className = flipped ? "card answer" : "card";
  el.replaceChildren(
    document.createTextNode(flipped ? card.answer : card.question),
    node("small", flipped ? `From slide ${card.slide}. Click to see the question.` : "Click to see the answer."),
  );
  $("card-count").textContent = `${cardIndex + 1} of ${cards.length}`;
  $("show-slide").textContent = slideOpen ? "Hide slide" : `Show slide ${card.slide}`;
  drawSlide();
}

function drawSlide() {
  // The PDF page the current card came from, shown under the card.
  const box = $("slide");
  box.hidden = !slideOpen;
  const wanted = slideOpen ? `${slidesFor}#${cards[cardIndex].slide}` : null;
  if (wanted === slideShown) return; // flipping a card must not reload the PDF
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
    box.replaceChildren(node("p", "No more lectures in the timetable."));
    $("brief").hidden = true;
    return;
  }
  const when = `${fmtDay(lec.start)}, ${fmtTime(lec.start)} to ${fmtTime(lec.end)}`;
  const heading = node("h2", lec.prep ? lec.prep.topic : lec.title);
  const details = [lec.room, lec.lecturer, `Week ${lec.week}`].filter(Boolean).join(" · ");
  const label = lec.past ? "Past lecture" : in24h ? "Next lecture, within 24 hours" : shown ? "Upcoming lecture" : "Next lecture";
  const parts = [];
  if (shown) {
    const back = node("button", "Back to next lecture", "back");
    back.onclick = () => { shown = null; refresh(); };
    parts.push(back);
  }
  parts.push(
    node("p", `${label} · ${lec.module} ${lec.title}`, "muted"),
    heading,
    node("p", `${when} · ${details}`),
    node("span", STATUS[lec.status], `badge ${lec.status}`),
  );
  if (lec.status === "waiting") {
    parts.push(node("p", "Nothing to do. The brief appears here when the slides are out.", "muted"));
  }
  if (lec.prep && lec.prep.slides_file) {
    parts.push(node("p", `Slides filed as ${lec.prep.slides_file}`, "muted"));
  }
  box.replaceChildren(...parts);

  $("brief").hidden = !lec.prep;
  if (!lec.prep) { cardsFor = null; return; }

  const prep = lec.prep;
  $("overview").textContent = prep.overview;
  fill($("covers"), prep.covers, (text) => node("li", text));
  fill($("questions"), prep.questions, (text) => node("li", text));
  $("link").textContent = prep.link_to_last_week;
  $("terms").replaceChildren(...prep.key_terms.flatMap((t) => [node("dt", t.term), node("dd", t.definition)]));

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

function drawHistory(data) {
  // Every lecture that has a brief, past weeks included, one module at a time.
  const picker = $("history-module");
  const modules = [...new Map(data.history.map((lec) => [lec.module, lec.title])).entries()];
  if (picker.options.length !== modules.length) {
    const keep = picker.value;
    fill(picker, modules, ([code, title]) => {
      const option = node("option", `${code} ${title}`);
      option.value = code;
      return option;
    });
    if (keep) picker.value = keep;
  }
  picker.hidden = modules.length === 0;
  const rows = data.history.filter((lec) => lec.module === picker.value);
  if (rows.length === 0) {
    $("history").replaceChildren(node("li", "Nothing yet. Briefs stay here after each lecture."));
    return;
  }
  fill($("history"), rows, (lec) => {
    const li = node("li");
    if (data.next && lec.id === data.next.id) li.className = "shown";
    li.append(node("strong", `Week ${lec.week}: ${lec.topic}`), node("div", fmtDay(lec.start) + (lec.past ? "" : " · upcoming"), "muted"));
    li.onclick = () => { shown = lec.id; refresh(); window.scrollTo(0, 0); };
    return li;
  });
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

  // Redraw only when something changed, so clicks and text selection are not interrupted.
  const snapshot = JSON.stringify({ ...data, now: null, module: $("history-module").value });
  if (snapshot === lastDrawn) return;
  lastDrawn = snapshot;
  drawLecture(data.next, data.next && data.next_24h.includes(data.next.id));
  fillJump(data.upcoming);

  fill($("upcoming"), data.upcoming, (lec) => {
    const li = node("li");
    if (data.next && lec.id === data.next.id) li.className = "shown";
    li.append(
      node("strong", `${lec.module} ${lec.title}`),
      node("div", `${fmtDay(lec.start)}, ${fmtTime(lec.start)} · ${lec.room}`, "muted"),
      node("span", STATUS[lec.status], `badge ${lec.status}`),
    );
    li.onclick = () => { shown = lec.id; refresh(); };
    return li;
  });

  $("notice").hidden = !data.notice;
  $("notice").textContent = data.notice || "";
  drawHistory(data);

  fill($("activity"), [...data.activity].reverse(), (item) => node("li", `${item.time}  ${item.text}`));
}

$("card").onclick = () => { flipped = !flipped; drawCard(); };
$("show-slide").onclick = () => { slideOpen = !slideOpen; drawCard(); };
$("next").onclick = () => { cardIndex = (cardIndex + 1) % cards.length; flipped = false; drawCard(); };
$("prev").onclick = () => { cardIndex = (cardIndex - 1 + cards.length) % cards.length; flipped = false; drawCard(); };

$("history-module").onchange = () => { lastDrawn = ""; refresh(); };

$("jump").onchange = async (event) => {
  await fetch("/api/clock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ at: event.target.value || null }),
  });
  shown = null;
  refresh();
};

refresh();
setInterval(refresh, 2000);
