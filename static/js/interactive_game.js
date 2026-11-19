// Вибір варіанта НЕ відправляє форму автоматично.
// Перевірка виконується тільки кнопкою «Перевірити відповідь».
// Без JavaScript звичайна HTML-форма також працює (атрибут required).
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('io-answer-form');
    if (!form) return;

    const submitButton = form.querySelector('button[type="submit"]');
    const radios = form.querySelectorAll('input[type="radio"][name="answer"]');
    if (!submitButton || !radios.length) return;

    // Кнопка активна тільки після вибору варіанта.
    const refreshButton = () => {
        submitButton.disabled = !Array.from(radios).some((radio) => radio.checked);
    };
    radios.forEach((radio) => radio.addEventListener('change', refreshButton));
    refreshButton();

    // Захист від подвійного натискання після початку відправлення.
    let submitting = false;
    form.addEventListener('submit', (event) => {
        if (submitting) {
            event.preventDefault();
            return;
        }
        submitting = true;
        submitButton.disabled = true;
        submitButton.textContent = 'Перевіряємо...';
    });
});
