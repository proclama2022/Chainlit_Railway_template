// script.js
document.getElementById('chatbotIcon').addEventListener('click', function() {
    var iframe = document.getElementById('chatIframe');
    var chatbotFrame = document.getElementById('chatbotFrame');
    // Verifica se l'iframe ha già caricato l'URL
    if (iframe.getAttribute("src") === "about:blank") {
        iframe.src = iframe.getAttribute("data-src"); // Imposta l'URL effettivo
    }
    chatbotFrame.style.display = "block"; // Mostra l'iframe
    closeButton.style.display = "block"; // Mostra il pulsante di chiusura
});


document.getElementById('closeButton').addEventListener('click', function() {
    var iframe = document.getElementById('chatbotFrame');
    iframe.style.display = "none";
    this.style.display = "none"; // Nasconde il pulsante di chiusura
});
