const Max = require('max-api');
const fs = require('fs');
const io = require('socket.io-client');

// Set up WebSocket connection
const socket = io('http://localhost:5000', {
    transports: ['websocket'],
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    randomizationFactor: 0.5,
    timeout: 300000,
    pingTimeout: 240000,
    pingInterval: 120000
});

let isProcessing = false;
let xValue = 0.5; // Default interpolation value
let scaleActive = false; // Default values for the toggles
let rotateActive = false;
let nonlinearActive = false;

let scaleValue = 1.0; // Default values for the numboxes
let rotateValue = 0.3;
let nonlinearValue = 0.5;

const timeoutDuration = 500;

// Initialize WebSocket connection and event listeners
function initSocketConnection() {
    socket.on('connect', () => {
        Max.post('Connected to WebSocket server.');
    });

    socket.on('disconnect', (reason) => {
        Max.post(`Disconnected: ${reason}`);
    });

    socket.on('interpolation_complete', (data) => {
        isProcessing = false;
        Max.post('Interpolation complete.');
        const outputBuffer = Buffer.from(data.audio_data, 'base64');
        fs.writeFileSync('C:/latent-mixer/outputInterpolated.wav', outputBuffer);
        Max.outlet('interpolation_complete');
    });

    socket.on('error', (data) => {
        isProcessing = false;
        Max.post(`Error: ${data.message}`);
        Max.outlet('error', data.message);
    });
}

// Set the slider value without triggering the interpolation
Max.addHandler('slider_value', (value) => {
    xValue = Math.round(value * 1000) / 1000;  // Rounds to three decimal places
    Max.post(`Slider value set to: ${xValue}`);
});

// Handlers for setting the values of the toggles
Max.addHandler('scale_active', (value) => {
    scaleActive = value === 1;
    Max.post(`Scale active set to: ${scaleActive}`);
});

Max.addHandler('rotate_active', (value) => {
    rotateActive = value === 1;
    Max.post(`Rotate active set to: ${rotateActive}`);
});

Max.addHandler('nonlinear_active', (value) => {
    nonlinearActive = value === 1;
    Max.post(`Nonlinear active set to: ${nonlinearActive}`);
});

// Handlers for setting the values of the numboxes
Max.addHandler('scale_value', (value) => {
    scaleValue = value;
    Max.post(`Scale value set to: ${scaleValue}`);
});

Max.addHandler('rotate_value', (value) => {
    rotateValue = value;
    Max.post(`Rotate value set to: ${rotateValue}`);
});

Max.addHandler('nonlinear_value', (value) => {
    nonlinearValue = value;
    Max.post(`Nonlinear value set to: ${nonlinearValue}`);
});

// Function to send buffers for interpolation
function sendBuffersForInterpolation(file1Path, file2Path, xValue) {
    fs.readFile(file1Path, (err1, data1) => {
        if (err1) {
            Max.post(`Error reading ${file1Path}: ${err1}`);
            return;
        }
        fs.readFile(file2Path, (err2, data2) => {
            if (err2) {
                Max.post(`Error reading ${file2Path}: ${err2}`);
                return;
            }
            const buffer1_base64 = data1.toString('base64');
            const buffer2_base64 = data2.toString('base64');

            socket.emit('interpolate_audio', {
                buffer1: buffer1_base64,
                buffer2: buffer2_base64,
                x: xValue,
                transforms: {
                    scale: scaleValue,
                    rotate: rotateValue,
                    nonlinear: nonlinearValue,
                    scale_active: scaleActive,
                    rotate_active: rotateActive,
                    nonlinear_active: nonlinearActive,
                },
            });
        });
    });
}

// Max message handlers
Max.addHandler('bang', () => {
    if (!isProcessing) {
        isProcessing = true;
        Max.post('Sending interpolation request...');
        sendBuffersForInterpolation('C:/latent-mixer/myBuffer.wav', 'C:/latent-mixer/myBuffer2.wav', xValue);
    } else {
        Max.post('Processing already in progress.');
    }
});

socket.on('connect_response', (data) => {
    Max.post('Connected to WebSocket server: ' + data.status);
});

Max.addHandler('test', () => {
    socket.emit('test_event', { message: 'Hello, WebSocket!' });
});

socket.on('test_event_response', (data) => {
    Max.post('Received response: ' + data.message);
});

// Start WebSocket connection
initSocketConnection();
