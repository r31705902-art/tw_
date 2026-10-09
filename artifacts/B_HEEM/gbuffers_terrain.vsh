#version 120

varying vec2 texcoord;
varying vec4 color;

uniform float frameTimeCounter;
uniform vec3 cameraPosition;

attribute vec4 mc_Entity;

void main() {
    texcoord = (gl_TextureMatrix[0] * gl_Vertex).xy;
    color = gl_Color;

    vec4 position = gl_Vertex;

    // Waving Leaves and Grass
    float wavingSpeed = 1.0;
    float wavingAmplitude = 0.1;

    // Check for leaves (ID 18, 161) and grass (ID 31, 175)
    if (mc_Entity.x == 18.0 || mc_Entity.x == 161.0 || mc_Entity.x == 31.0 || mc_Entity.x == 175.0) {
        position.x += sin(frameTimeCounter * wavingSpeed + position.x + position.y + position.z) * wavingAmplitude;
        position.z += cos(frameTimeCounter * wavingSpeed + position.x + position.y + position.z) * wavingAmplitude;
    }

    gl_Position = gl_ModelViewProjectionMatrix * position;
}
