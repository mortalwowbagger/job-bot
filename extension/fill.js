// job-bot: fill the application form on this page with the user's packet.
// Injected by the popup only when the user clicks "Fill this application".
// Never submits, never navigates, never answers work-authorization, sponsorship,
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
    return clean(parts.join(" ").replace(/[*✱]/g, ""));
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
      .filter(visible);
  }

  const done = [];
  const used = new Set();

  function fill(what, value, selectors, labelRe, attrRe, notRe) {
    if (!value) return false;
    const ok = (el) => el && visible(el) && !el.value && !used.has(el) && !SENSITIVE.test(labelText(el));
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

  window.jobbotFill = function (p) {
    done.length = 0;
    used.clear();
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

    const notes = [];
    if (p.files && p.files.letter && !done.includes("cover letter") && !done.includes("cover letter (text)") &&
        /cover\s*letter/i.test(document.body.innerText || "")) {
      notes.push("This form asks for a cover letter but has no upload box yet: click its Attach button and choose the Cover Letter PDF from job-bot.");
    }
    return { frame: location.host, filled: [...done], notes };
  };
})();
