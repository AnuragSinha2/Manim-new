document.addEventListener('DOMContentLoaded', () => {
    const topicInput = document.getElementById('topic-input');
    const generateBtn = document.getElementById('generate-animation-btn');
    const stopBtn = document.getElementById('stop-generation-btn');
    const qualitySelect = document.getElementById('quality-select');
    const voiceSelect = document.getElementById('voice-select');
    const modelSelect = document.getElementById('model-select');
    
    const outputSection = document.querySelector('.output-section');
    const outputLog = document.getElementById('output-log');
    const animationOutput = document.getElementById('animation-output');
    const imageComponentsOutput = document.getElementById('image-components-output');
    const scriptOutput = document.getElementById('script-output');
    const narrationOutput = document.getElementById('narration-output');
    const audioPlayerContainer = document.getElementById('audio-player-container');
    const audioPlayer = document.getElementById('audio-player');
    const downloadScriptBtn = document.getElementById('download-script-btn');
    const downloadNarrationBtn = document.getElementById('download-narration-btn');
    const statusOverlay = document.querySelector('.status-overlay');
    const statusText = document.getElementById('status-text');
    const tabs = document.querySelectorAll('.tab-link');
    const tabContents = document.querySelectorAll('.tab-content');

    let socket;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(item => item.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tab + '-tab');
            tabContents.forEach(content => content.classList.remove('active'));
            target.classList.add('active');
        });
    });

    function setControlsDisabled(disabled) {
        topicInput.disabled = disabled;
        generateBtn.disabled = disabled;
        qualitySelect.disabled = disabled;
        voiceSelect.disabled = disabled;
        modelSelect.disabled = disabled;
        stopBtn.classList.toggle('hidden', !disabled);
        generateBtn.classList.toggle('hidden', disabled);
    }

    function clearOutputs() {
        outputLog.textContent = '';
        scriptOutput.textContent = '';
        narrationOutput.textContent = '';
        animationOutput.innerHTML = '';
        imageComponentsOutput.innerHTML = '';
        audioPlayerContainer.classList.add('hidden');
        downloadScriptBtn.classList.add('hidden');
        downloadNarrationBtn.classList.add('hidden');
    }

    generateBtn.addEventListener('click', () => {
        const topic = topicInput.value.trim();
        if (!topic) {
            alert('Please enter a topic.');
            return;
        }

        const quality = qualitySelect.value;
        const voice = voiceSelect.value;
        const model = modelSelect.value;

        // Disable controls
        setControlsDisabled(true);

        // Show output section
        outputSection.classList.remove('hidden');
        statusOverlay.classList.remove('hidden');
        
        // Clear previous outputs
        clearOutputs();

        // Open WebSocket connection
        socket = new WebSocket(`ws://${window.location.host}/ws/generate-full-animation`);

        socket.onopen = () => {
            console.log("WebSocket connection established.");
            socket.send(JSON.stringify({ type: "start", topic, quality, voice, model }));
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log("Received data:", data);

            if (data.status === 'progress' || data.status === 'error' || data.status === 'completed') {
                const stage = data.stage ? `[${data.stage}] ` : '';
                const message = `${stage}${data.message}\n`;
                outputLog.textContent += message;
                statusText.textContent = data.message;
            }

            if (data.status === 'error' || data.status === 'completed') {
                setControlsDisabled(false);
                if (data.status === 'completed') {
                    statusOverlay.classList.add('hidden');
                }
            }

            if (data.narration) {
                narrationOutput.textContent = data.narration;
                downloadNarrationBtn.classList.remove('hidden');
            }
            if (data.script) {
                scriptOutput.textContent = data.script;
                downloadScriptBtn.classList.remove('hidden');
            }
            if (data.output_file) {
                animationOutput.innerHTML = `<video controls src="${data.output_file}" type="video/mp4"></video>`;
            }
            if (data.tts_audio_url) {
                audioPlayer.src = data.tts_audio_url;
                audioPlayerContainer.classList.remove('hidden');
            }
            if (data.image_components) {
                imageComponentsOutput.innerHTML = '<h4>Generated Image Components:</h4>';
                data.image_components.forEach(img => {
                    const imgCard = document.createElement('div');
                    imgCard.className = 'image-card';
                    
                    const imgEl = document.createElement('img');
                    imgEl.src = img.path;
                    imgEl.alt = img.description;
                    
                    const pEl = document.createElement('p');
                    pEl.textContent = img.description;
                    
                    imgCard.appendChild(imgEl);
                    imgCard.appendChild(pEl);
                    imageComponentsOutput.appendChild(imgCard);
                });
            }
        };

        socket.onclose = () => {
            console.log("WebSocket connection closed.");
            setControlsDisabled(false);
        };

        socket.onerror = (error) => {
            console.error("WebSocket error:", error);
            outputLog.textContent += "A connection error occurred. Please check the server logs.\n";
            setControlsDisabled(false);
        };
    });

    stopBtn.addEventListener('click', () => {
        if (socket) {
            socket.send(JSON.stringify({ type: "stop" }));
        }
    });

    downloadScriptBtn.addEventListener('click', () => {
        const blob = new Blob([scriptOutput.textContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'manim_script.py';
        a.click();
        URL.revokeObjectURL(url);
    });

    downloadNarrationBtn.addEventListener('click', () => {
        const blob = new Blob([narrationOutput.textContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'narration.txt';
        a.click();
        URL.revokeObjectURL(url);
    });
});