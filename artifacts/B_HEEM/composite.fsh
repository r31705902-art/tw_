#version 120

varying vec2 texcoord;

uniform sampler2D gcolor;
uniform sampler2D gnormal;
uniform sampler2D depthtex0;

uniform mat4 gbufferProjection;
uniform mat4 gbufferProjectionInverse;

uniform float wetness;

void main() {
    vec3 color = texture2D(gcolor, texcoord).rgb;
    float depth = texture2D(depthtex0, texcoord).r;

    if (depth == 1.0) {
        gl_FragColor = vec4(color, 1.0);
        return;
    }

    // Basic Rain Reflection
    if (wetness > 0.0) {
        vec3 normal = texture2D(gnormal, texcoord).rgb * 2.0 - 1.0;
        
        // Simple reflection logic (very basic)
        if (normal.y > 0.7) { // Only reflect on top surfaces
            vec4 pos = gbufferProjectionInverse * vec4(texcoord * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
            pos /= pos.w;
            
            vec3 reflectDir = reflect(normalize(pos.xyz), normal);
            
            // Sample color from reflection direction (very simplified)
            vec2 reflectCoord = texcoord + reflectDir.xy * 0.1 * wetness;
            vec3 reflectColor = texture2D(gcolor, reflectCoord).rgb;
            
            color = mix(color, reflectColor, 0.2 * wetness);
        }
    }

    gl_FragColor = vec4(color, 1.0);
}
