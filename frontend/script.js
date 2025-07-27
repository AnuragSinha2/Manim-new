document.addEventListener('DOMContentLoaded', () => {
    const topicInput = document.getElementById('topic-input');
    const generateBtn = document.getElementById('generate-animation-btn');
    const stopBtn = document.getElementById('stop-generation-btn');
    const qualitySelect = document.getElementById('quality-select');
    const voiceSelect = document.getElementById('voice-select');
    
    const outputSection = document.querySelector('.output-section');
    const outputLog = document.getElementById('output-log');
    const animationOutput = document.getElementById('animation-output');
    const scriptOutput = document.getElementById('script-output');
    const narrationOutput = document.getElementById('narration-output');
    
    const downloadScriptBtn = document.getElementById('download-script-btn');
    const downloadNarrationBtn = document.getElementById('download-narration-btn');
    
    const audioPlayerContainer = document.getElementById('audio-player-container');
    const audioPlayer = document.getElementById('audio-player');
    
    const statusOverlay = document.querySelector('.status-overlay');
    const statusText = document.getElementById('status-text');

    const tabs = document.querySelectorAll('.tab-link');
    const tabContents = document.querySelectorAll('.tab-content');

    let socket = null;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(item => item.classList.remove('active'));
            tab.classList.add('active');

            const targetTab = document.querySelector(`#${tab.dataset.tab}-tab`);
            tabContents.forEach(content => content.classList.remove('active'));
            targetTab.classList.add('active');
        });
    });

    function generateAnimation() {
        const topic = topicInput.value.trim();
        if (!topic) {
            alert('Please enter a topic.');
            return;
        }

        const quality = qualitySelect.value;
        const voice = voiceSelect.value;

        outputSection.classList.remove('hidden');
        statusOverlay.classList.remove('hidden');
        statusText.textContent = 'Connecting to server...';
        
        outputLog.textContent = '';
        scriptOutput.textContent = '';
        narrationOutput.textContent = '';
        animationOutput.innerHTML = '';
        audioPlayerContainer.classList.add('hidden');
        audioPlayer.src = '';
        downloadScriptBtn.classList.add('hidden');
        downloadNarrationBtn.classList.add('hidden');
        
        generateBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/generate-full-animation`);

        socket.onopen = () => {
            logMessage('Connection established. Sending topic to AI...');
            statusText.textContent = 'Generating script with AI...';
            socket.send(JSON.stringify({ type: 'start', topic: topic, quality: quality, voice: voice }));
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.status === 'progress') {
                logMessage(`[${data.stage}] ${data.message}`);
                statusText.textContent = `${data.stage}...`;
            } else if (data.status === 'completed') {
                logMessage('Animation completed!');
                statusOverlay.classList.add('hidden');
                if (data.output_file) {
                    const videoEl = document.createElement('video');
                    videoEl.src = data.output_file; 
                    videoEl.controls = true;
                    videoEl.playsInline = true;
                    animationOutput.innerHTML = '';
                    animationOutput.appendChild(videoEl);
                }
                socket.close();
            } else if (data.status === 'error') {
                logMessage(`ERROR: ${data.message}`);
                statusText.textContent = `Error: ${data.message}`;
                socket.close();
            }

            if (data.script) {
                scriptOutput.textContent = data.script;
                downloadScriptBtn.classList.remove('hidden');
            }
            if (data.narration) {
                narrationOutput.textContent = data.narration;
                downloadNarrationBtn.classList.remove('hidden');
            }
            if (data.tts_audio_url) {
                audioPlayer.src = data.tts_audio_url;
                audioPlayerContainer.classList.remove('hidden');
            }
        };

        socket.onclose = () => {
            logMessage('Connection closed.');
            generateBtn.classList.remove('hidden');
            stopBtn.classList.add('hidden');
            if (!statusText.textContent.startsWith('Error')) {
                statusText.textContent = 'Finished';
            }
        };

        socket.onerror = (event) => {
            console.error("WebSocket error:", event);
            logMessage('WebSocket Error: Connection failed. Please check the server logs.');
            statusText.textContent = 'Connection Error';
        };
    }

    function stopGeneration() {
        if (socket) {
            socket.send(JSON.stringify({ type: 'stop' }));
        }
    }

    function logMessage(message) {
        outputLog.textContent += message + '\n';
        outputLog.scrollTop = outputLog.scrollHeight;
    }

    function downloadFile(filename, content) {
        const element = document.createElement('a');
        element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(content));
        element.setAttribute('download', filename);
        element.style.display = 'none';
        document.body.appendChild(element);
        element.click();
        document.body.removeChild(element);
    }

    generateBtn.addEventListener('click', generateAnimation);
    stopBtn.addEventListener('click', stopGeneration);
    downloadScriptBtn.addEventListener('click', () => {
        downloadFile('script.py', scriptOutput.textContent);
    });
    downloadNarrationBtn.addEventListener('click', () => {
        downloadFile('narration.txt', narrationOutput.textContent);
    });
});
