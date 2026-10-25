/* Versioned MOCK-only display renderer. No services, project reads or operations. */
"use strict";
(() => {
  const states = Object.freeze({
    complete: "Complete", active: "Active", planned: "Planned", blocked: "Blocked",
    approval: "Approval Required", built: "Built", tested: "Tested", missing: "Missing",
    next: "Next", not_evaluated: "Not Evaluated", not_cleared: "Not Cleared", unverified: "Unverified"
  });
  const categories = ["Engineering", "AI/ML", "Strategy", "Financial Performance", "Risk", "GitHub/Publication"];
  const phases = ["Past Engineering", "Engineering", "Exploratory Research", "Future Validation", "Trading Readiness"];
  function shape(value, keys) {
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) throw new Error("Invalid object shape");
  }
  function texts(value, fields) {
    for (const field of fields) if (typeof value[field] !== "string" || !value[field].trim() || value[field].length > 3000) throw new Error("Invalid text");
  }
  function list(value, maximum = 20) {
    if (!Array.isArray(value) || !value.length || value.length > maximum) throw new Error("Invalid list");
  }
  function unique(value, field) {
    if (new Set(value.map(item => item[field])).size !== value.length) throw new Error("Duplicate item");
  }
  function status(value, allowed) {
    if (typeof value !== "string" || !allowed.includes(value)) throw new Error("Invalid status");
  }
  function validate(data) {
    shape(data, ["schemaVersion", "mock", "freshness", "health", "roadmap", "current", "latest", "decision"]);
    if (data.schemaVersion !== 3 || data.mock !== true) throw new Error("Only schema v3 MOCK DATA is accepted");
    shape(data.freshness, ["lastVerifiedUpdate", "sourceSha", "localState", "publishedState", "note"]);
    texts(data.freshness, Object.keys(data.freshness));
    const date = data.freshness.lastVerifiedUpdate;
    const parsed = new Date(date);
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(date) || !Number.isFinite(parsed.getTime()) || parsed.toISOString().replace(".000Z", "Z") !== date) throw new Error("Invalid fictional timestamp");
    if (!/^MOCK-[A-Z0-9-]{4,80}$/.test(data.freshness.sourceSha)) throw new Error("Source identifier must be explicitly fictional");
    status(data.freshness.localState, ["Local", "Unverified"]);
    status(data.freshness.publishedState, ["Published", "Unverified"]);
    list(data.health, 6);
    unique(data.health, "category");
    if (data.health.length !== 6 || categories.some(category => !data.health.some(item => item.category === category))) throw new Error("Missing health category");
    for (const item of data.health) {
      shape(item, ["category", "status", "value", "description", "tested", "missing", "blocked", "limitations"]);
      texts(item, ["category", "value", "description", "tested", "missing", "blocked", "limitations"]);
      status(item.status, ["built", "tested", "blocked", "not_evaluated", "not_cleared", "unverified"]);
    }
    list(data.roadmap, 8);
    unique(data.roadmap, "id");
    if (data.roadmap.filter(item => item.status === "active").length !== 1 || phases.some(phase => !data.roadmap.some(item => item.phase === phase))) throw new Error("Ambiguous active milestone or missing phase");
    for (const item of data.roadmap) {
      shape(item, ["id", "title", "phase", "status", "description", "readiness", "components"]);
      texts(item, ["id", "title", "phase", "description"]);
      if (!/^mock-[a-z0-9-]+$/.test(item.id) || !phases.includes(item.phase)) throw new Error("Invalid mock milestone");
      status(item.status, ["complete", "active", "planned", "blocked", "approval"]);
      shape(item.readiness, ["built", "tested", "missing", "blocked", "next"]);
      texts(item.readiness, Object.keys(item.readiness));
      list(item.components, 8);
      unique(item.components, "title");
      for (const component of item.components) {
        shape(component, ["title", "status", "description", "steps"]);
        texts(component, ["title", "description"]);
        status(component.status, ["built", "tested", "missing", "blocked", "next"]);
        list(component.steps, 8);
        unique(component.steps, "title");
        for (const step of component.steps) {
          shape(step, ["title", "status", "description"]);
          texts(step, ["title", "description"]);
          status(step.status, ["built", "tested", "missing", "blocked", "next"]);
        }
      }
    }
    shape(data.current, ["milestoneId", "building", "unresolved", "requirements", "limitations"]);
    texts(data.current, ["milestoneId", "building", "unresolved", "limitations"]);
    if (!data.roadmap.some(item => item.id === data.current.milestoneId && item.status === "active")) throw new Error("Current milestone is not active");
    list(data.current.requirements, 8);
    for (const requirement of data.current.requirements) texts({ requirement }, ["requirement"]);
    shape(data.latest, ["title", "changed", "why", "verification", "limitations", "impacts", "technical"]);
    texts(data.latest, ["title", "changed", "why", "verification", "limitations"]);
    if (!data.latest.verification.startsWith("MOCK ONLY:")) throw new Error("Verification must be fictional");
    list(data.latest.impacts, 5);
    unique(data.latest.impacts, "category");
    if (data.latest.impacts.length !== 5 || categories.slice(0, 5).some(category => !data.latest.impacts.some(item => item.category === category))) throw new Error("Missing impact category");
    for (const impact of data.latest.impacts) {
      shape(impact, ["category", "description"]);
      texts(impact, ["category", "description"]);
    }
    list(data.latest.technical, 10);
    for (const line of data.latest.technical) texts({ line }, ["line"]);
    shape(data.decision, ["title", "status", "description", "boundary"]);
    texts(data.decision, ["title", "description", "boundary"]);
    status(data.decision.status, ["approval"]);
    return data;
  }
  function node(tag, className, content, direction = "ltr") {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    element.dir = direction;
    if (direction === "rtl") element.lang = "ar";
    return element;
  }
  function arabic(tag, className, content) { return node(tag, className, content, "rtl"); }
  function badge(value) { return node("span", "badge " + value, states[value]); }
  function facts(entries, className = "evidence-facts") {
    const dl = node("dl", className);
    for (const [label, description] of entries) {
      const row = node("div", "fact");
      row.append(node("dt", "", label), arabic("dd", "", description));
      dl.append(row);
    }
    return dl;
  }
  function disclosure(label, className = "") {
    const details = node("details", className);
    details.append(node("summary", "", label));
    return details;
  }
  const ids = ["freshness-data", "health-grid", "roadmap-list", "current-data", "latest-data", "decision-data"];
  function render(input) {
    try {
      validate(input);
      const data = JSON.parse(JSON.stringify(input));
      const error = document.getElementById("data-error");
      error.hidden = true;
      error.textContent = "";
      for (const id of ids) document.getElementById(id).replaceChildren();
      const freshness = document.getElementById("freshness-data");
      for (const [label, value] of [
        ["Last Verified Update · MOCK", data.freshness.lastVerifiedUpdate.replace("T", " ").replace("Z", " UTC")],
        ["Source SHA · MOCK", data.freshness.sourceSha],
        ["Local / Published State · MOCK", data.freshness.localState + " / " + data.freshness.publishedState]
      ]) {
        const cell = node("div", "freshness-cell");
        cell.append(node("span", "freshness-label", label), node("code", "", value));
        freshness.append(cell);
      }
      freshness.append(arabic("p", "freshness-note", data.freshness.note));
      for (const item of data.health) {
        const card = node("article", "health-card");
        const top = node("div", "health-card-top");
        top.append(node("h3", "", item.category), badge(item.status));
        const details = disclosure("Evidence & Gaps", "health-details");
        details.append(facts([["Built / Tested · MOCK", item.tested], ["Missing", item.missing], ["Blocked", item.blocked], ["Evidence Limitations", item.limitations]]));
        card.append(top, node("p", "health-value", item.value), arabic("p", "health-detail", item.description), details);
        document.getElementById("health-grid").append(card);
      }
      data.roadmap.forEach((item, index) => {
        const stage = node("article", "stage");
        stage.dataset.state = item.status;
        const number = node("span", "stage-number", String(index + 1).padStart(2, "0"));
        number.setAttribute("aria-hidden", "true");
        const details = node("details", "milestone-details");
        const summary = node("summary");
        const titleBlock = node("span", "stage-title-block");
        titleBlock.append(node("span", "stage-title", item.title), node("small", "stage-phase", item.phase));
        summary.append(titleBlock, badge(item.status));
        const body = node("div", "details-body");
        body.append(arabic("p", "", item.description), facts(Object.entries(item.readiness).map(([key, value]) => [states[key], value]), "readiness-grid"), node("h4", "components-heading", "Components & Substeps"));
        for (const component of item.components) {
          const componentDetails = disclosure("", "component-details");
          componentDetails.children[0].append(node("span", "component-title", component.title), badge(component.status));
          const componentBody = node("div", "component-body");
          const steps = node("ul", "substeps");
          for (const step of component.steps) {
            const li = node("li");
            const heading = node("div", "substep-heading");
            heading.append(node("strong", "", step.title), badge(step.status));
            li.append(heading, arabic("p", "", step.description));
            steps.append(li);
          }
          componentBody.append(arabic("p", "component-purpose", component.description), steps);
          componentDetails.append(componentBody);
          body.append(componentDetails);
        }
        details.append(summary, body);
        stage.append(number, details);
        document.getElementById("roadmap-list").append(stage);
      });
      const milestone = data.roadmap.find(item => item.id === data.current.milestoneId);
      const current = document.getElementById("current-data");
      const requirements = node("ul", "requirements");
      for (const requirement of data.current.requirements) requirements.append(arabic("li", "", requirement));
      current.append(node("h3", "current-name", milestone.title), facts([["Building", data.current.building], ["Unresolved", data.current.unresolved]]), node("h4", "components-heading", "Completion Requirements"), requirements, arabic("p", "limitation", data.current.limitations));
      const latest = document.getElementById("latest-data");
      const impacts = disclosure("Impact by Area", "impact-details");
      impacts.append(facts(data.latest.impacts.map(item => [item.category, item.description])));
      const technical = disclosure("Technical Details · MOCK", "technical-details");
      const technicalBody = node("div", "details-body");
      for (const line of data.latest.technical) technicalBody.append(node("code", "", line));
      technical.append(technicalBody);
      latest.append(node("h3", "latest-title", data.latest.title), facts([["What Changed", data.latest.changed], ["Why It Matters", data.latest.why]]), node("h4", "components-heading", "Verification · MOCK ONLY"), arabic("p", "test-note", data.latest.verification), arabic("p", "limitation", data.latest.limitations), impacts, technical);
      document.getElementById("decision-data").append(node("h3", "", data.decision.title), badge(data.decision.status), arabic("p", "", data.decision.description), arabic("p", "boundary", data.decision.boundary));
      return true;
    } catch (_) {
      for (const id of ids) document.getElementById(id).replaceChildren();
      const error = document.getElementById("data-error");
      error.textContent = "تعذر عرض العينة الخيالية: بيانات مفقودة أو غير صالحة أو متناقضة. لا توجد حالة بديلة أو بيانات مشروع حقيقية.";
      error.dir = "rtl";
      error.lang = "ar";
      error.hidden = false;
      return false;
    }
  }
  const navigation = document.querySelectorAll("nav a");
  for (const link of navigation) link.addEventListener("click", () => {
    for (const other of navigation) other.removeAttribute("aria-current");
    link.setAttribute("aria-current", "location");
  });
  if (navigation.length) navigation[0].setAttribute("aria-current", "location");
  window.ProjectControlPrototype = Object.freeze({ validate, render });
  render(window.PROJECT_CONTROL_MOCK);
})();
