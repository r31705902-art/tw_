#version 120

varying vec2 texcoord;

uniform sampler2D gcolor;

void main() {
    gl_FragColor = texture2D(gcolor, texcoord);
}
