
// Пошук створених ігор

const searchInput = document.getElementById("game-search");
const gameCards = document.querySelectorAll(".game-card");
const searchEmpty = document.getElementById("search-empty");

if (searchInput) {
    searchInput.addEventListener("input", function () {
        const query = this.value.trim().toLowerCase();

        let visibleCount = 0;

        gameCards.forEach(function (card) {
            const gameText = card.dataset.search || "";
            const matches = gameText.includes(query);

            card.hidden = !matches;

            if (matches) {
                visibleCount++;
            }
        });

        if (searchEmpty) {
            searchEmpty.hidden = visibleCount > 0;
        }
    });
}


// Копіювання посилання на гру

const copyButtons = document.querySelectorAll(".copy-game-link");

copyButtons.forEach(function (button) {
    button.addEventListener("click", async function () {
        const link = button.dataset.url;

        if (!link) {
            return;
        }

        try {
            await navigator.clipboard.writeText(link);

            button.textContent = "Скопійовано!";

            setTimeout(function () {
                button.textContent = "Скопіювати посилання";
            }, 2000);

        } catch (error) {
            // Якщо браузер не дозволяє копіювання,
            // показуємо посилання для ручного копіювання.
            window.prompt(
                "Скопіюйте посилання на гру:",
                link
            );
        }
    });
});
