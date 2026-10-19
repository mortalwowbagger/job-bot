// job-bot: fill the application form on this page with the user's packet.
// Injected by the popup only when the user clicks "Fill this application".
// Never submits or navigates (the only thing it clicks is a form's own "Add another"
// employment row and "Current role" box), never answers work-authorization, sponsorship,
// salary, EEO or other sensitive questions. Fields that already have a value are left alone.
(() => {
  const SENSITIVE = /authori[sz]|sponsor|visa|citizen|salary|compensation|pay\s*expect|gender|pronoun|race|ethnic|hispanic|latin|veteran|disab|criminal|background\s*check|date\s*of\s*birth|\bage\b|ssn|social\s*security/i;

  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) &&
    !el.disabled && !el.readOnly && getComputedStyle(el).visibility !== "hidden";

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

  function labelText(el) {
    const parts = [];
    if (el.labels) for (const l of el.labels) parts.push(l.innerText);
    if (el.getAttribute("aria-label")) parts.push(el.getAttribute("aria-label"));
    const by = el.getAttribute("aria-labelledby");
    if (by) for (const id of by.split(/\s+/)) { const n = document.getElementById(id); if (n) parts.push(n.innerText); }
    if (!clean(parts.join(""))) parts.push(nearbyLabel(el));
    return clean(parts.join(" ").replace(/[*✱]/g, "").replace(/\s*:\s*$/, ""));
  }

  // Forms whose <label>s aren't tied to their inputs: use the label (or short text) just before the input
  function nearbyLabel(el) {
    let node = el;
    for (let depth = 0; depth < 3 && node; depth++, node = node.parentElement) {
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
        if (sib.matches("input, textarea, select") || sib.querySelector("input, textarea, select")) return "";
        const text = clean(sib.innerText);
        if (text && text.length <= 80) return text;
        if (text) return "";
      }
    }
    return "";
  }
  // label plus attributes, for matching
  const describe = (el) => clean([labelText(el), el.placeholder, el.name, el.id, el.getAttribute("autocomplete")].join(" "));

  function setValue(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value); // works with React-controlled inputs
    for (const t of ["input", "change", "blur"]) el.dispatchEvent(new Event(t, { bubbles: true }));
  }

  function textFields() {
    return [...document.querySelectorAll(
      "input:not([type]), input[type=text], input[type=email], input[type=tel], input[type=url], textarea")]
      .filter((el) => visible(el) && el.getAttribute("role") !== "combobox");
  }

  const done = [];
  const used = new Set();

  function fill(what, value, selectors, labelRe, attrRe, notRe) {
    if (!value) return false;
    const ok = (el) => el && visible(el) && !el.value && !used.has(el) && !SENSITIVE.test(labelText(el)) &&
      el.getAttribute("role") !== "combobox";
    for (const sel of selectors || []) {
      const el = document.querySelector(sel);
      if (ok(el)) { setValue(el, value); used.add(el); done.push(what); return true; }
    }
    for (const el of textFields()) {
      if (!ok(el)) continue;
      const lab = labelText(el);
      if (notRe && notRe.test(lab)) continue;
      if ((labelRe && lab && labelRe.test(lab)) || (attrRe && attrRe.test(clean([el.name, el.id, el.getAttribute("autocomplete")].join(" "))))) {
        setValue(el, value); used.add(el); done.push(what); return true;
      }
    }
    return false;
  }

  function b64ToFile(f) {
    const bin = atob(f.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], f.name, { type: "application/pdf" });
  }

  // the input's own label plus the text of its surrounding block, stopping before
  // a block that also holds another upload box (so labels don't bleed across)
  function fileContext(el) {
    let ctx = describe(el);
    let n = el.parentElement;
    for (let i = 0; i < 4 && n && n.querySelectorAll("input[type=file]").length === 1; i++, n = n.parentElement) {
      ctx += " " + clean(n.innerText).slice(0, 160);
    }
    return ctx;
  }

  function attach(input, file, what) {
    const dt = new DataTransfer();
    dt.items.add(b64ToFile(file));
    input.files = dt.files;
    for (const t of ["input", "change"]) input.dispatchEvent(new Event(t, { bubbles: true }));
    done.push(what);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(id, ms = 3000) {
    for (let t = 0; t < ms / 100; t++) { if (document.getElementById(id)) return true; await sleep(100); }
    return false;
  }
  // the "Add another" link belonging to this section: the first one after the given field,
  // as long as no field of a later section (school/degree) sits in between
  function addAnotherAfter(field) {
    if (!field) return null;
    const links = [...document.querySelectorAll("a, button")].filter((b) => /^\s*add another\s*$/i.test(b.innerText || ""));
    const nextSection = document.querySelector("[id^=school--], [id^=degree--]");
    return links.find((b) => (field.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      !(nextSection && (nextSection.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING))) || null;
  }

  // standard <select> dropdowns for state / country (never ones inside surveys)
  function selectNative(c) {
    const norm = (s) => (s || "").toLowerCase().replace(/[^a-z ]/g, "").trim();
    for (const el of [...document.querySelectorAll("select")].filter(visible)) {
      if (el.value || used.has(el) || /survey|eeo/i.test(el.name || "") || el.closest("[class*=survey], [class*=eeo]")) continue;
      const lab = labelText(el);
      if (SENSITIVE.test(lab)) continue;
      let wants = null, what = null;
      if (/^(state|province)\b/i.test(lab) && (c.state || c.state_name)) { wants = [c.state, c.state_name]; what = "state"; }
      else if (/^country\b/i.test(lab) && c.country) {
        wants = [c.country].concat(/united states/i.test(c.country) ? ["United States of America", "USA", "US"] : []); what = "country";
      }
      if (!wants) continue;
      const opt = [...el.options].find((o) => wants.some((w) => w && (norm(o.text) === norm(w) || norm(o.value) === norm(w))));
      if (opt) {
        el.value = opt.value;
        for (const t of ["input", "change"]) el.dispatchEvent(new Event(t, { bubbles: true }));
        used.add(el); done.push(what);
      }
    }
  }

  // Lever's "Current location" only accepts a pick from its suggestions: type the city, choose the match
  async function leverLocation(c, query) {
    const input = document.getElementById("location-input");
    if (!input || input.value || !visible(input)) return;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    input.focus();
    let v = "";
    for (const ch of query) {
      v += ch;
      input.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true }));
      set.call(input, v);
      input.dispatchEvent(new InputEvent("input", { data: ch, inputType: "insertText", bubbles: true }));
      input.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true }));
      await sleep(30);
    }
    for (let t = 0; t < 25; t++) {
      await sleep(200);
      const opts = [...document.querySelectorAll(".dropdown-location")];
      if (!opts.length) continue;
      const pick = opts.find((o) => o.innerText.toLowerCase().includes((c.city || "").toLowerCase())) || opts[0];
      for (const ev of ["mousedown", "mouseup", "click"]) pick.dispatchEvent(new MouseEvent(ev, { bubbles: true }));
      used.add(input); done.push("location");
      return;
    }
    notes.push("Choose your location from the Current location suggestions.");
  }

  const notes = [];

  window.jobbotFill = async function (p) {
    notes.length = 0;
    done.length = 0;
    used.clear();
    let rows = 0;
    const c = p.contact || {};
    const full = clean(`${c.first_name || ""} ${c.last_name || ""}`);

    // names: split fields first, then a single full-name field (anchored: never "Name Pronunciation")
    // a label naming both ("First & Last Name") is a full-name field, not a first/last one
    fill("first name", c.first_name, ["#first_name"], /(^|\b)(legal\s+|preferred\s+)?(first|given)\s*name\b/i, /first.?name|given.?name|fname/i, /last|family|surname/i);
    fill("last name", c.last_name, ["#last_name"], /(^|\b)(legal\s+)?(last|family)\s*name\b|surname/i, /last.?name|family.?name|surname|lname/i, /first|given/i);
    fill("full name", full, ["#_systemfield_name", "input[name=name]"],
      /^((full|legal|preferred|your)\s+)?((first|given)\s*(&|and)\s*(last|family)\s*)?name$/i, null);
    fill("email", c.email, ["#email", "#_systemfield_email", "input[name=email]", "input[type=email]"], /e-?mail/i, /e-?mail/i);
    fill("phone", c.phone, ["#phone", "input[name=phone]", "input[type=tel]"], /phone|mobile|cell/i, /phone|mobile|tel/i);
    fill("LinkedIn", c.linkedin, ["input[name='urls[LinkedIn]']"], /linkedin/i, /linkedin/i);
    fill("GitHub", c.github, ["input[name='urls[GitHub]']"], /github/i, /github/i);
    fill("current company", c.current_company, ["input[name=org]"], /^current\s+(company|employer)/i, null);

    // Employment section (Greenhouse ids): every job in the profile, newest first. Extra rows
    // are added with the section's own "Add another" link. Months are set by select.js.
    const jobs = (p.employment || []).slice(0, 10);
    if (jobs.length && document.getElementById("company-name-0")) {
      for (let i = 0; i < jobs.length; i++) {
        if (i > 0 && !document.getElementById(`company-name-${i}`)) {
          const add = addAnotherAfter(document.getElementById(`company-name-${i - 1}`));
          if (!add) break;
          add.click();
          if (!(await waitFor(`company-name-${i}`))) break;
        }
        const job = jobs[i];
        const n = done.length;
        fill("employer", job.company, [`#company-name-${i}`]);
        fill("job title", job.title, [`#title-${i}`]);
        fill("start year", job.start_year, [`#start-date-year-${i}`]);
        if (job.current) {
          const box = document.querySelector(`input[type=checkbox][id^=current-role-${i}]`);
          if (box && !box.checked) { box.click(); done.push("current role"); }
        } else {
          fill("end year", job.end_year, [`#end-date-year-${i}`]);
        }
        if (done.length > n) rows++;
      }
      // one summary entry instead of six "employer, job title, ..." repeats
      const keep = done.filter((d) => !["employer", "job title", "start year", "end year", "current role"].includes(d));
      done.length = 0; done.push(...keep);
      if (rows) done.push(`employment (${rows} job${rows > 1 ? "s" : ""})`);
    }

    // Address: only what the profile has (street/ZIP are optional there). Location-preference
    // questions ("preferred office", "willing to relocate") are left alone.
    const NOT_LOC = /prefer|office|relocat|willing|which location|work from/i;
    const cityState = [c.city, c.state].filter(Boolean).join(", ");
    if (document.getElementById("location-input") && cityState) await leverLocation(c, cityState);
    fill("street address", c.address, [], /^(street|home|mailing|residential)?\s*address(\s*line)?\s*1?$|^street/i,
         /address.?line.?1|street/i, /e-?mail|web|url|\bip\b|link/i);
    fill("city", c.city, [], /^(current\s+)?city\b|^town\b/i, /^city$|address.?city/i, /citizen|state/i);
    fill("state", c.state, [], /^(state|province|region)\b/i, /^state$|address.?state/i);
    fill("ZIP", c.postal_code, [], /zip|postal/i, /zip|postal/i);
    fill("country", c.country, [], /^country\b/i, /^country$/i, /citizen/i);
    fill("location", cityState, [], /^(current\s+)?location\b|where (are you|do you) (currently )?(located|based|live)|^city,?\s*(and|&|\/)?\s*state/i,
         null, NOT_LOC);
    selectNative(c);

    // cover letter as text, where a form asks for it in a box (Lever "additional information" etc.)
    const letterBox = [...document.querySelectorAll("textarea")].filter(visible)
      .find((el) => !el.value && !used.has(el) && (/cover\s*letter/i.test(describe(el)) || el.name === "comments"));
    if (letterBox && p.cover_letter) { setValue(letterBox, p.cover_letter); used.add(letterBox); done.push("cover letter (text)"); }

    // files: the resume goes to the resume input, the cover letter to its own input if there is one
    const inputs = [...document.querySelectorAll("input[type=file]")].filter((el) => !el.disabled && !(el.files && el.files.length));
    // the box's own label decides; surrounding text only when it has no label of its own
    const RESUME = /resume|r[ée]sum[ée]|\bcv\b|curriculum/i, COVER = /cover/i;
    const kind = inputs.map((el) => {
      const own = describe(el);
      if (COVER.test(own)) return "cover";
      if (RESUME.test(own)) return "resume";
      const ctx = fileContext(el);
      return COVER.test(ctx) ? "cover" : RESUME.test(ctx) ? "resume" : "";
    });
    const isCover = (i) => kind[i] === "cover";
    const isResume = (i) => kind[i] === "resume";
    // "Autofill from resume" / import boxes only parse a file; prefer the real resume field
    const helper = (i) => /autofill|auto-fill|import|parse/i.test(describe(inputs[i]));
    let r = inputs.findIndex((el, i) => isResume(i) && !helper(i) && /resume|cv/i.test(describe(el)));
    if (r < 0) r = inputs.findIndex((el, i) => isResume(i) && !helper(i));
    if (r < 0) r = inputs.findIndex((el, i) => isResume(i));
    if (r < 0 && inputs.length === 1 && !isCover(0)) r = 0;
    if (r >= 0 && p.files && p.files.resume) attach(inputs[r], p.files.resume, "resume");
    const cl = inputs.findIndex((el, i) => i !== r && isCover(i));
    if (cl >= 0 && p.files && p.files.letter) attach(inputs[cl], p.files.letter, "cover letter");

    if (p.files && p.files.letter && !done.includes("cover letter") && !done.includes("cover letter (text)") &&
        /cover\s*letter/i.test(document.body.innerText || "")) {
      notes.push("This form asks for a cover letter but has no upload box yet: click its Attach button and choose the Cover Letter PDF from job-bot.");
    }
    return { frame: location.host, filled: [...done], notes: [...notes] };
  };
})();
