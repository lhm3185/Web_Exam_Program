document.addEventListener("DOMContentLoaded", () => {
  const kind = document.getElementById("id_kind");
  const choices = document.getElementById("choices-group");
  const referenceAnswer = document.getElementById("id_reference_answer");
  if (!kind || !choices || !referenceAnswer) {
    return;
  }

  const referenceRow = referenceAnswer.closest(".form-row");
  const initialForms = document.getElementById("id_choices-INITIAL_FORMS");
  const hasExistingChoices = Number(initialForms.value) > 0;
  const hasChoiceErrors = choices.querySelector(".errorlist") !== null;
  const hint = document.createElement("p");
  hint.className = "help";
  hint.id = "question-kind-hint";
  hint.setAttribute("aria-live", "polite");
  kind.closest(".form-row").append(hint);
  kind.setAttribute("aria-describedby", hint.id);

  const instructions = {
    choice: "보기를 두 개 이상 입력하고 정답 하나를 체크하세요.",
    written: "문제와 배점을 입력하고, 채점할 때 참고할 모범 답안을 적을 수 있습니다.",
    code: "문제에 보드와 요구 동작을 적고, 채점할 때 참고할 예시 코드를 입력할 수 있습니다.",
  };

  function updateQuestionForm() {
    const isChoice = kind.value === "choice";
    const showChoices = isChoice || hasExistingChoices || hasChoiceErrors;
    choices.hidden = !showChoices;
    referenceRow.hidden = isChoice;
    referenceAnswer.disabled = isChoice;
    referenceAnswer.spellcheck = kind.value !== "code";
    for (const input of choices.querySelectorAll("input:not([type=hidden]), select, textarea")) {
      input.disabled = !showChoices;
    }
    hint.textContent = instructions[kind.value] || "";
    if (!isChoice && hasExistingChoices) {
      hint.textContent += " 유형을 바꾸려면 기존 보기에서 삭제를 모두 체크하고 저장하세요.";
    }
  }

  kind.addEventListener("change", updateQuestionForm);
  updateQuestionForm();
});
