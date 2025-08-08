document.addEventListener('DOMContentLoaded', () => {
    const topicInput = document.getElementById('topic-input');
    const urlInput = document.getElementById('url-input');
    const pdfInput = document.getElementById('pdf-input');
    const generateBtn = document.getElementById('generate-animation-btn');
    const stopBtn = document.getElementById('stop-generation-btn');
    const qualitySelect = document.getElementById('quality-select');
    const voiceSelect = document.getElementById('voice-select');
    const themeSelect = document.getElementById('theme-select');
    const modelSelect = document.getElementById('model-select');

    // Populate voice options
    const voices = [
        "achernar", "achird", "algenib", "algieba", "alnilam", "aoede", "autonoe", 
        "callirrhoe", "charon", "despina", "enceladus", "erinome", "fenrir", 
        "gacrux", "iapetus", "kore", "laomedeia", "leda", "orus", "puck", 
        "pulcherrima", "rasalgethi", "sadachbia", "sadaltager", "schedar", 
        "sulafat", "umbriel", "vindemiatrix", "zephyr", "zubenelgenubi"
    ];
    voices.forEach(voice => {
        const option = document.createElement('option');
        option.value = voice;
        option.textContent = voice.charAt(0).toUpperCase() + voice.slice(1);
        voiceSelect.appendChild(option);
    });
        voiceSelect.value = 'achernar'; // Set default voice
    
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

    function showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        
        toast.className = 'show';
        if (type === 'error') {
            toast.classList.add('error');
        } else if (type === 'success') {
            toast.classList.add('success');
        }

        setTimeout(() => {
            toast.className = toast.className.replace('show', '');
        }, 3000);
    }

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
        urlInput.disabled = disabled;
        generateBtn.disabled = disabled;
        qualitySelect.disabled = disabled;
        voiceSelect.disabled = disabled;
        themeSelect.disabled = disabled;
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

    generateBtn.addEventListener('click', async () => {
        const topic = topicInput.value.trim();
        const url = urlInput.value.trim();
        const pdfFile = pdfInput.files[0];

        if (!topic && !url && !pdfFile) {
            showToast('Please enter a topic, a URL, or select a PDF file.', 'error');
            return;
        }

        let pdfPath = null;
        if (pdfFile) {
            const formData = new FormData();
            formData.append('file', pdfFile);

            try {
                const response = await fetch('/upload-pdf', {
                    method: 'POST',
                    body: formData,
                });
                const result = await response.json();
                if (response.ok) {
                    pdfPath = result.path;
                    showToast('PDF uploaded successfully!', 'success');
                } else {
                    throw new Error(result.detail || 'PDF upload failed.');
                }
            } catch (error) {
                showToast(error.message, 'error');
                return;
            }
        }

        const quality = qualitySelect.value;
        const voice = voiceSelect.value;
        const theme = themeSelect.value;
        const model = modelSelect.value;

        setControlsDisabled(true);
        generateBtn.classList.add('loading');
        outputSection.classList.remove('hidden');
        statusOverlay.classList.remove('hidden');
        
        clearOutputs();

        console.log("Attempting to open WebSocket connection...");
        socket = new WebSocket(`ws://${window.location.host}/ws/generate-full-animation`);

        socket.onopen = () => {
            console.log("WebSocket connection established.");
            showToast('Connection established. Starting generation...');
            socket.send(JSON.stringify({ type: "start", topic, url, pdf_path: pdfPath, quality, voice, theme, model }));
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log("Received data:", data);

            if (data.status === 'progress' || data.status === 'error' || data.status === 'completed') {
                const stage = data.stage ? `[${data.stage}] ` : '';
                const message = `${stage}${data.message}\n`;
                outputLog.textContent += message;
                outputLog.scrollTop = outputLog.scrollHeight;
                statusText.textContent = data.message;

                if (data.status === 'error') {
                    showToast(data.message, true);
                }
                if (data.stage === 'Cancelled') {
                    showToast('Animation generation stopped.');
                }
            }

            if (data.status === 'error' || data.status === 'completed') {
                setControlsDisabled(false);
                generateBtn.classList.remove('loading');
                if (data.status === 'completed') {
                    statusOverlay.classList.add('hidden');
                    if (data.output_file) {
                        showToast('Animation generated successfully!');
                    }
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
                // The audio is now part of the main video, so we can hide the separate player.
                audioPlayerContainer.classList.add('hidden');
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
            generateBtn.classList.remove('loading');
        };

        socket.onerror = (error) => {
            console.error("WebSocket error:", error);
            showToast('A connection error occurred. Please check the server logs.', true);
            setControlsDisabled(false);
            generateBtn.classList.remove('loading');
        };
    });

    stopBtn.addEventListener('click', () => {
        if (socket) {
            socket.close();
            showToast('Stopping generation...');
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

    // Theme switcher logic
    const themeSwitch = document.getElementById('checkbox');
    themeSwitch.addEventListener('change', () => {
        if (themeSwitch.checked) {
            document.body.classList.remove('light-mode');
            document.body.classList.add('dark-mode');
            localStorage.setItem('theme', 'dark-mode');
        } else {
            document.body.classList.remove('dark-mode');
            document.body.classList.add('light-mode');
            localStorage.setItem('theme', 'light-mode');
        }
    });

    // Set initial theme
    const currentTheme = localStorage.getItem('theme');
    if (currentTheme) {
        document.body.classList.add(currentTheme);
        if (currentTheme === 'dark-mode') {
            themeSwitch.checked = true;
        }
    } else {
        document.body.classList.add('light-mode');
    }
});