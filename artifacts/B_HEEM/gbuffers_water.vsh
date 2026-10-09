#version 120

varying vec2 texcoord;
varying vec4 color;

uniform float frameTimeCounter;

attribute vec4 mc_Entity;

void main() {
    texcoord = (gl_TextureMatrix[0] * gl_Vertex).xy;
    color = gl_Color;

    vec4 position = gl_Vertex;

    // Waving Water
    float wavingSpeed = 1.5;
    float wavingAmplitude = 0.05;

    // Check for water (ID 8, 9)
    if (mc_Entity.x == 8.0 || mc_Entity.x == 9.0) {
        position.y += sin(frameTimeCounter * wavingSpeed + position.x + position.z) * wavingAmplitude;
    }

    gl_Position = gl_ModelViewProjectionMatrix * position;
}
