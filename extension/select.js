// job-bot: choose options in searchable dropdowns (react-select, used by Greenhouse's
// Employment / Education sections). Runs in the page's own context because these
// dropdowns ignore simulated typing; we call the dropdown's own select method instead.
// Only touches dropdowns that are still empty; never anything sensitive.
window.jobbotSelects = async function (p) {
  const filled = [], notes = [];
  const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9&' ]+/g, " ").replace(/\s+/g, " ").trim();
  const STOP = new Set(["of", "the", "at", "and", "in", "for", "a"]);
  const words = (s) => norm(s).split(" ").filter((w) => w && !STOP.has(w));

  function selectFor(input) {
    const key = input && Object.keys(input).find((k) => k.startsWith("__reactFiber"));
    let f = key && input[key];
    for (let d = 0; f && d < 40; d++, f = f.return) {
      if (f.stateNode && typeof f.stateNode.selectOption === "function") return f.stateNode;
    }
    return null;
  }
  const hasValue = (sel) => {
    try { return (sel.getValue ? sel.getValue() : []).length > 0; } catch (e) { return false; }
  };

  async function options(sel, query) {
    let opts = sel.props.options || [];
    if ((!opts.length || sel.props.loadOptions) && sel.props.loadOptions && query) {
      const res = await new Promise((resolve) => {
        const timer = setTimeout(() => resolve([]), 4000);
        const done = (r) => { clearTimeout(timer); resolve(r); };
        try {
          const out = sel.props.loadOptions(query, [], { page: 1 });
          if (out && out.then) out.then(done, () => done([])); else done(out);
        } catch (e) { done([]); }
      });
      opts = Array.isArray(res) ? res : (res && res.options) || [];
    }
    return opts.flatMap((o) => (Array.isArray(o.options) ? o.options : [o]));
  }
  const label = (o) => o.label ?? o.name ?? "";

  // best option: exact, then starts-with, then the one covering most of the wanted words
  function best(opts, want, minCover) {
    const w = norm(want);
    let pick = opts.find((o) => norm(label(o)) === w) || opts.find((o) => norm(label(o)).startsWith(w));
    if (pick) return pick;
    const ww = words(want);
    let top = null, score = 0;
    for (const o of opts) {
      const ow = new Set(words(label(o)));
      const cover = ww.filter((x) => ow.has(x)).length / Math.max(ww.length, 1);
      const extra = [...ow].filter((x) => !ww.includes(x)).length;
      const s = cover - extra * 0.01;
      if (cover >= minCover && s > score) { score = s; top = o; }
    }
    return top;
  }

  async function choose(input, what, queries, minCover = 1) {
    const sel = selectFor(input);
    if (!sel || hasValue(sel)) return false;
    for (const q of queries.filter(Boolean)) {
      const pick = best(await options(sel, q), queries[0], minCover);
      if (pick) { sel.selectOption(pick); filled.push(what); return true; }
    }
    return false;
  }

  const byId = (re) => [...document.querySelectorAll("input[role=combobox]")].find((el) => re.test(el.id));

  const job = (p.employment || [])[0];
  if (job) {
    if (job.start_month) await choose(byId(/^start-date-month-0$/), "start month", [job.start_month]);
    if (job.end_month && !job.current) await choose(byId(/^end-date-month-0$/), "end month", [job.end_month]);
  }

  const edu = (p.education || []).find((e) => e.school);
  const school = byId(/^school--0$/);
  if (school && !edu) {
    if ((p.education || []).length) notes.push("Your education is a plain line of text; use School / Degree / Field in your profile so it can be filled.");
    else notes.push("Add your education to your job-bot profile to fill the Education section.");
  }
  if (edu) {
    const name = edu.school;
    const ws = words(name);
    const queries = [name, name.replace(/\s+at\s+/i, " - "), ws.slice(0, 3).join(" "),
                     [...ws].sort((a, b) => b.length - a.length)[0]];
    if (school && !(await choose(school, "school", queries, 1))) {
      if (!hasValue(selectFor(school) || {})) notes.push(`Couldn't find "${name}" in this form's school list; pick it yourself.`);
    }
    const d = edu.degree || "";
    const degreeQ = /^\s*b\.?\s?[sa]\.?|bachelor/i.test(d) ? ["Bachelor"] :
      /mba/i.test(d) ? ["MBA", "Master"] : /^\s*m\.?\s?[sa]\.?|master/i.test(d) ? ["Master"] :
      /^\s*a\.?\s?[as]\.?|associate/i.test(d) ? ["Associate"] : /ph\.?\s?d|doctor/i.test(d) ? ["Doctor", "Ph.D"] :
      /high\s*school|ged/i.test(d) ? ["High School"] : [d];
    if (d) await choose(byId(/^degree--0$/), "degree", degreeQ, 0.5);
    if (edu.field) await choose(byId(/^discipline--0$/), "discipline", [edu.field, words(edu.field)[0]], 1);
  }
  return { filled, notes };
};
