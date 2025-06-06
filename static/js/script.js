document.addEventListener('DOMContentLoaded', function() {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    
    let estadoActual = 0;
    let contextoConversacion = {};

    // Saludo inicial con retraso para simular carga
    setTimeout(() => {
        enviarMensajeBot('¡Hola! Soy EPASBot, tu asistente para la Etapa Productiva. 😊<br><br>¿En qué puedo ayudarte hoy?');
        
        // Mostrar opciones después de 1 segundo
        setTimeout(() => {
            enviarMensajeBot('Por favor selecciona una opción:<br>' +
                            '1. 📄 Consultar estado de documentos<br>' +
                            '2. ❓ Preguntas frecuentes<br>' +
                            '3. ℹ️ Información sobre etapa productiva');
            estadoActual = 4; // MENU_PRINCIPAL
        }, 1000);
    }, 500);

    sendBtn.addEventListener('click', procesarMensaje);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') procesarMensaje();
    });



   function mostrarProceso(proceso) {
        const procesoDiv = document.createElement('div');
        procesoDiv.className = 'proceso-texto';
        
        // Mostrar solo los últimos 3 pasos para no saturar
        const pasosRecientes = proceso.slice(-3);
        procesoDiv.innerHTML = pasosRecientes.join('<br>');
        
        return procesoDiv;
    }

  function procesarMensaje() {
        const mensaje = userInput.value.trim();
        if (mensaje === '') return;
        
        mostrarMensaje(mensaje, 'user');
        userInput.value = '';
        
        // Mostrar indicador de que el bot está escribiendo
        const typingIndicator = document.createElement('div');
        typingIndicator.id = 'typing-indicator';
        typingIndicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
        chatBox.appendChild(typingIndicator);
        chatBox.scrollTop = chatBox.scrollHeight;
        
        fetch('/procesar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                estado: estadoActual,
                mensaje: mensaje,
                contexto: contextoConversacion
            })
        })
        .then(response => response.json())
        .then(data => {
            // Eliminar indicador de escritura
            document.getElementById('typing-indicator')?.remove();
            
            // Actualizar estado y contexto
            estadoActual = data.estado;
            contextoConversacion = data.contexto || {};
            
            // Mostrar respuesta del bot
            if (data.mensaje) {
                enviarMensajeBot(data.mensaje);
            }
            
            // Mostrar proceso si existe
            if (data.proceso && data.proceso.length > 0) {
                const procesoDiv = mostrarProceso(data.proceso);
                chatBox.appendChild(procesoDiv);
                chatBox.scrollTop = chatBox.scrollHeight;
            }
            
            // Manejar final de conversación
            if (data.mostrar_reinicio) {
                userInput.disabled = true;
                sendBtn.disabled = true;
                
                const nuevoBtn = document.createElement('button');
                nuevoBtn.textContent = 'Hacer otra consulta';
                nuevoBtn.className = 'btn btn-restart';
                nuevoBtn.onclick = reiniciarChat;
                chatBox.appendChild(nuevoBtn);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('typing-indicator')?.remove();
            enviarMensajeBot('⚠️ Lo siento, hubo un error. Por favor intenta nuevamente.');
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


