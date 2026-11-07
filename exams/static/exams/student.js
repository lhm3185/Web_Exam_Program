const form = document.getElementById("answer-form");
const timer = document.getElementById("time-left");
const status = document.getElementById("save-status");
const revision = form.elements.namedItem("revision");
const saveUrl = form.getAttribute("action");
const submitButton = document.getElementById("final-submit");
const confirmation = document.getElementById("submit-confirmation");
const confirmSubmit = document.getElementById("confirm-submit");
const cancelSubmit = document.getElementById("cancel-submit");

let deadline = performance.now() + Number(form.dataset.remainingMs);
let editVersion = 0;
let savedVersion = 0;
let scheduledSave;
let pendingSave;
let submitting = false;
let blocked = false;
let leaving = false;

function openReceipt() {
  leaving = true;
  window.location.replace(form.dataset.examUrl);
}

function scheduleSave(delay) {
  clearTimeout(scheduledSave);
  scheduledSave = setTimeout(() => {
    if (!submitting && !blocked && editVersion !== savedVersion) {
      persist("save");
    }
  }, delay);
}

function persist(action) {
  if (pendingSave) {
    return pendingSave;
  }

  const version = editVersion;
  const data = new FormData(form);
  data.set("action", action);
  status.textContent = action === "submit" ? "제출 중…" : "저장 중…";

  pendingSave = (async () => {
    try {
      const response = await fetch(saveUrl, {
        method: "POST",
        headers: {Accept: "application/json"},
        body: data,
      });
      if (response.status === 409 || response.status === 403) {
        blocked = true;
        const body = await response.json().catch(() => ({}));
        status.textContent = body.error || "응시 코드로 다시 접속하세요.";
        return false;
      }
      if (response.status === 400) {
        const body = await response.json().catch(() => ({}));
        status.textContent = body.error || "답안 내용을 확인하세요.";
        return false;
      }
      if (!response.ok) {
        throw new Error("Answer save failed");
      }
      const result = await response.json();
      revision.value = result.revision;
      savedVersion = version;
      deadline = Math.min(deadline, performance.now() + result.remaining_ms);
      if (result.submitted) {
        openReceipt();
      } else if (editVersion === savedVersion) {
        status.textContent = "답안을 저장했습니다.";
      } else {
        status.textContent = "변경한 답안 저장 대기 중";
        scheduleSave(1000);
      }
      return true;
    } catch {
      status.textContent = "연결을 확인하세요. 마지막으로 저장된 답안은 서버에 보관됩니다.";
      if (action === "save" && performance.now() < deadline) {
        scheduleSave(5000);
      }
      return false;
    } finally {
      pendingSave = null;
    }
  })();
  return pendingSave;
}

form.addEventListener("input", () => {
  editVersion += 1;
  if (!blocked && !submitting) {
    status.textContent = "변경한 답안 저장 대기 중";
    scheduleSave(deadline - performance.now() < 4000 ? 0 : 1800);
  }
});

async function sendManual(action) {
  if (submitting || blocked || leaving) {
    return;
  }

  submitting = true;
  clearTimeout(scheduledSave);
  form.querySelectorAll("button").forEach(button => { button.disabled = true; });
  try {
    if (pendingSave) {
      await pendingSave;
    }
    if (!blocked && !leaving) {
      await persist(action);
    }
  } finally {
    submitting = false;
    if (!blocked && !leaving) {
      form.querySelectorAll("button").forEach(button => { button.disabled = false; });
    }
  }
}

function showConfirmation(visible) {
  confirmation.hidden = !visible;
  submitButton.setAttribute("aria-expanded", String(visible));
  (visible ? confirmSubmit : submitButton).focus();
}

form.addEventListener("submit", event => {
  event.preventDefault();
  if (submitting || blocked || leaving) {
    return;
  }

  if (event.submitter?.value === "submit") {
    showConfirmation(true);
  } else {
    sendManual("save");
  }
});

cancelSubmit.addEventListener("click", () => showConfirmation(false));
confirmSubmit.addEventListener("click", () => {
  showConfirmation(false);
  sendManual("submit");
});

function updateTimer() {
  const seconds = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  timer.textContent = minutes + ":" + String(seconds % 60).padStart(2, "0");
  if (seconds === 0 && !leaving) {
    if (navigator.onLine) {
      openReceipt();
    } else {
      status.textContent = "시간이 끝났습니다. 연결이 복구되면 제출 내역을 확인합니다.";
    }
  }
}

window.addEventListener("beforeunload", event => {
  if (!leaving && editVersion !== savedVersion) {
    event.preventDefault();
    event.returnValue = true;
  }
});
window.addEventListener("online", () => {
  updateTimer();
  if (!leaving && !blocked && editVersion !== savedVersion) {
    scheduleSave(0);
  }
});
updateTimer();
setInterval(updateTimer, 250);
