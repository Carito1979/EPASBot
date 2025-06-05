document.addEventListener('DOMContentLoaded', function() {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    
    let estadoActual = 0;

    // Iniciar conversación
    enviarMensajeBot('¡Hola! Soy tu asistente SENA. Por favor ingresa tu número de identificación para verificar el estado de los documentos de tu etapa productiva:');
    estadoActual = 1; // SOLICITAR_CEDULA

    sendBtn.addEventListener('click', procesarMensaje);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') procesarMensaje();
    });

    function procesarMensaje() {
        const mensaje = userInput.value.trim();
        if (mensaje === '') return;
        
        mostrarMensaje(mensaje, 'user');
        userInput.value = '';
        
        fetch('/procesar', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                estado: estadoActual,
                mensaje: mensaje
            })
        })
        .then(response => response.json())
        .then(data => {
            estadoActual = data.estado;
            enviarMensajeBot(data.mensaje);
            
            if (estadoActual === 2) { // FINAL
                userInput.disabled = true;
                sendBtn.disabled = true;
                
                // Botón para nueva consulta
                const nuevoBtn = document.createElement('button');
                nuevoBtn.textContent = 'Hacer otra consulta';
                nuevoBtn.className = 'help-btn';
                nuevoBtn.onclick = reiniciarChat;
                chatBox.appendChild(nuevoBtn);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            enviarMensajeBot('⚠️ Error de conexión. Intenta nuevamente.');
        });
    }

    function reiniciarChat() {
        chatBox.innerHTML = '';
        userInput.disabled = false;
        sendBtn.disabled = false;
        estadoActual = 0;
        enviarMensajeBot('¡Hola! Soy tu asistente SENA. Por favor ingresa tu número de identificación para verificar el estado de los documentos de tu etapa productiva:');
        estadoActual = 1;
    }

    function enviarMensajeBot(mensaje) {
        mostrarMensaje(mensaje, 'bot');
    }

   function mostrarMensaje(mensaje, tipo) {
        const divMensaje = document.createElement('div');
        divMensaje.classList.add('message', `${tipo}-message`);
        divMensaje.innerHTML = mensaje;  
        chatBox.appendChild(divMensaje);
        chatBox.scrollTop = chatBox.scrollHeight;
    }


});
