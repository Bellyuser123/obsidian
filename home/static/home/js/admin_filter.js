document.addEventListener('DOMContentLoaded', function() {
    const isSpecialJudge = document.querySelector('#id_is_special_judge');
    const scriptField = document.querySelector('.field-special_judge_script');

    function toggleScript() {
        if (isSpecialJudge.checked) {
            scriptField.style.display = 'block';
        } else {
            scriptField.style.display = 'none';
        }
    }

    if (isSpecialJudge && scriptField) {
        isSpecialJudge.addEventListener('change', toggleScript);
        toggleScript(); // Run on load
    }
});