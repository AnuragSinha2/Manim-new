document.addEventListener('DOMContentLoaded', () => {
    const topicInput = document.getElementById('topic-input');
    const generateBtn = document.getElementById('generate-animation-btn');
    const outputLog = document.getElementById('output-log');
    const animationOutput = document.getElementById('animation-output');
    let socket = null;

    function generateAnimation() {
        const topic = topicInput.value.trim();
        if (!topic) {
            alert('Please enter a topic.');
            return;
        }

        outputLog.textContent = 'Starting animation generation...\n';
        // Do not clear the animation output, so we can have a grid of videos
        // animationOutput.innerHTML = ''; 
        generateBtn.disabled = true;

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/generate-full-animation`);

        socket.onopen = () => {
            outputLog.textContent += 'Connection established. Sending topic to AI...\n';
            socket.send(JSON.stringify({ topic: topic }));
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.status === 'progress') {
                // Append new log messages and scroll to the bottom
                outputLog.textContent += `\n[${data.stage}] ${data.message}`;
                outputLog.scrollTop = outputLog.scrollHeight;
            } else if (data.status === 'completed') {
                outputLog.textContent += '\n\nAnimation completed!\n';
                outputLog.scrollTop = outputLog.scrollHeight;
                if (data.output_file) {
                    const videoEl = document.createElement('video');
                    videoEl.src = data.output_file; 
                    videoEl.controls = true;
                    videoEl.playsInline = true;
                    videoEl.addEventListener('loadedmetadata', () => {
                        // Prepend the new video to the grid to show the latest first
                        animationOutput.prepend(videoEl);
                    });
                }
                socket.close();
            } else if (data.status === 'error') {
                outputLog.textContent += `\n\nERROR: ${data.message}\n`;
                outputLog.scrollTop = outputLog.scrollHeight;
                socket.close();
            }
        };

        socket.onclose = () => {
            outputLog.textContent += '\nConnection closed.';
            generateBtn.disabled = false;
        };

        socket.onerror = (event) => {
            console.error("WebSocket error:", event);
            outputLog.textContent += `\n\nWebSocket Error: Connection failed. Please check the server logs for more details.\n`;
            outputLog.scrollTop = outputLog.scrollHeight;
            generateBtn.disabled = false;
        };
    }

    generateBtn.addEventListener('click', generateAnimation);
});