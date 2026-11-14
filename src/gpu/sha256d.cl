/*
 * Bitcoin SHA-256d — midstate + nonce scan (OpenCL).
 * Only target-beating nonces are written with atomic (hashes are not copied to host).
 */

#define ROTR(x,n) (((x)>>(n))|((x)<<(32-(n))))
#define Ch(x,y,z) (((x)&(y))^((~(x))&(z)))
#define Maj(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))
#define S0(x) (ROTR((x),2)^ROTR((x),13)^ROTR((x),22))
#define S1(x) (ROTR((x),6)^ROTR((x),11)^ROTR((x),25))
#define s0(x) (ROTR((x),7)^ROTR((x),18)^((x)>>3))
#define s1(x) (ROTR((x),17)^ROTR((x),19)^((x)>>10))
#define BSWAP(x) ((((x)&0xFFu)<<24)|(((x)&0xFF00u)<<8)|(((x)&0xFF0000u)>>8)|(((x)>>24)&0xFFu))

__constant uint K[64] = {
    0x428A2F98u,0x71374491u,0xB5C0FBCFu,0xE9B5DBA5u,0x3956C25Bu,0x59F111F1u,0x923F82A4u,0xAB1C5ED5u,
    0xD807AA98u,0x12835B01u,0x243185BEu,0x550C7DC3u,0x72BE5D74u,0x80DEB1FEu,0x9BDC06A7u,0xC19BF174u,
    0xE49B69C1u,0xEFBE4786u,0x0FC19DC6u,0x240CA1CCu,0x2DE92C6Fu,0x4A7484AAu,0x5CB0A9DCu,0x76F988DAu,
    0x983E5152u,0xA831C66Du,0xB00327C8u,0xBF597FC7u,0xC6E00BF3u,0xD5A79147u,0x06CA6351u,0x14292967u,
    0x27B70A85u,0x2E1B2138u,0x4D2C6DFCu,0x53380D13u,0x650A7354u,0x766A0ABBu,0x81C2C92Eu,0x92722C85u,
    0xA2BFE8A1u,0xA81A664Bu,0xC24B8B70u,0xC76C51A3u,0xD192E819u,0xD6990624u,0xF40E3585u,0x106AA070u,
    0x19A4C116u,0x1E376C08u,0x2748774Cu,0x34B0BCB5u,0x391C0CB3u,0x4ED8AA4Au,0x5B9CCA4Fu,0x682E6FF3u,
    0x748F82EEu,0x78A5636Fu,0x84C87814u,0x8CC70208u,0x90BEFFFAu,0xA4506CEBu,0xBEF9A3F7u,0xC67178F2u
};

__kernel void sha256d_search(
    __global const uint *midstate,
    const uint tail0,
    const uint tail1,
    const uint tail2,
    const uint nonce_base,
    __global const uint *target_words,
    __global uint *out_nonces,
    __global uint *out_count,
    const uint max_out,
    const uint count
) {
    const uint tid = get_global_id(0);
    if (tid >= count) return;

    const uint nonce = nonce_base + tid;

    /* Midstate private — host caches while header[0:64] is fixed */
    const uint m0 = midstate[0];
    const uint m1 = midstate[1];
    const uint m2 = midstate[2];
    const uint m3 = midstate[3];
    const uint m4 = midstate[4];
    const uint m5 = midstate[5];
    const uint m6 = midstate[6];
    const uint m7 = midstate[7];

    uint w[64];
    w[0] = tail0;
    w[1] = tail1;
    w[2] = tail2;
    w[3] = BSWAP(nonce);
    w[4] = 0x80000000u;
#pragma unroll
    for (int i = 5; i < 15; i++) w[i] = 0;
    w[15] = 640u;

#pragma unroll
    for (int i = 16; i < 64; i++)
        w[i] = s1(w[i-2]) + w[i-7] + s0(w[i-15]) + w[i-16];

    uint a = m0, b = m1, c = m2, d = m3, e = m4, f = m5, g = m6, h = m7;

#pragma unroll
    for (int i = 0; i < 64; i++) {
        uint t1 = h + S1(e) + Ch(e,f,g) + K[i] + w[i];
        uint t2 = S0(a) + Maj(a,b,c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    uint h0 = a + m0;
    uint h1 = b + m1;
    uint h2 = c + m2;
    uint h3 = d + m3;
    uint h4 = e + m4;
    uint h5 = f + m5;
    uint h6 = g + m6;
    uint h7 = h + m7;

    w[0] = h0; w[1] = h1; w[2] = h2; w[3] = h3;
    w[4] = h4; w[5] = h5; w[6] = h6; w[7] = h7;
    w[8] = 0x80000000u;
#pragma unroll
    for (int i = 9; i < 15; i++) w[i] = 0;
    w[15] = 256u;

#pragma unroll
    for (int i = 16; i < 64; i++)
        w[i] = s1(w[i-2]) + w[i-7] + s0(w[i-15]) + w[i-16];

    a = 0x6A09E667u; b = 0xBB67AE85u; c = 0x3C6EF372u; d = 0xA54FF53Au;
    e = 0x510E527Fu; f = 0x9B05688Cu; g = 0x1F83D9ABu; h = 0x5BE0CD19u;

#pragma unroll
    for (int i = 0; i < 64; i++) {
        uint t1 = h + S1(e) + Ch(e,f,g) + K[i] + w[i];
        uint t2 = S0(a) + Maj(a,b,c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    h0 = a + 0x6A09E667u;
    h1 = b + 0xBB67AE85u;
    h2 = c + 0x3C6EF372u;
    h3 = d + 0xA54FF53Au;
    h4 = e + 0x510E527Fu;
    h5 = f + 0x9B05688Cu;
    h6 = g + 0x1F83D9ABu;
    h7 = h + 0x5BE0CD19u;

    /* LE uint32[8]; le[7] MSB — coarse filter first */
    const uint t7 = target_words[7];
    const uint le7 = BSWAP(h7);
    if (le7 > t7) return;
    if (le7 == t7) {
        const uint le6 = BSWAP(h6);
        const uint t6 = target_words[6];
        if (le6 > t6) return;
        if (le6 == t6) {
            uint le[6];
            le[0] = BSWAP(h0);
            le[1] = BSWAP(h1);
            le[2] = BSWAP(h2);
            le[3] = BSWAP(h3);
            le[4] = BSWAP(h4);
            le[5] = BSWAP(h5);
            int pass = 1;
#pragma unroll
            for (int i = 5; i >= 0; i--) {
                if (le[i] < target_words[i]) { pass = 1; break; }
                if (le[i] > target_words[i]) { pass = 0; break; }
            }
            if (!pass) return;
        }
    }

    uint slot = atomic_inc(out_count);
    if (slot < max_out) out_nonces[slot] = nonce;
}

/*
 * Verification: compute SHA-256d digest on GPU for each nonce in the list.
 * out_digest: 8x uint per nonce (h0..h7 big-endian SHA words).
 * Host struct.pack('>8I', ...) yields the same 32 bytes as hash256().
 */
__kernel void sha256d_hash_nonces(
    __global const uint *midstate,
    const uint tail0,
    const uint tail1,
    const uint tail2,
    __global const uint *nonces,
    __global uint *out_digest,
    const uint count
) {
    const uint tid = get_global_id(0);
    if (tid >= count) return;

    const uint nonce = nonces[tid];
    const uint m0 = midstate[0];
    const uint m1 = midstate[1];
    const uint m2 = midstate[2];
    const uint m3 = midstate[3];
    const uint m4 = midstate[4];
    const uint m5 = midstate[5];
    const uint m6 = midstate[6];
    const uint m7 = midstate[7];

    uint w[64];
    w[0] = tail0;
    w[1] = tail1;
    w[2] = tail2;
    w[3] = BSWAP(nonce);
    w[4] = 0x80000000u;
#pragma unroll
    for (int i = 5; i < 15; i++) w[i] = 0;
    w[15] = 640u;
#pragma unroll
    for (int i = 16; i < 64; i++)
        w[i] = s1(w[i-2]) + w[i-7] + s0(w[i-15]) + w[i-16];

    uint a = m0, b = m1, c = m2, d = m3, e = m4, f = m5, g = m6, h = m7;
#pragma unroll
    for (int i = 0; i < 64; i++) {
        uint t1 = h + S1(e) + Ch(e,f,g) + K[i] + w[i];
        uint t2 = S0(a) + Maj(a,b,c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    uint h0 = a + m0;
    uint h1 = b + m1;
    uint h2 = c + m2;
    uint h3 = d + m3;
    uint h4 = e + m4;
    uint h5 = f + m5;
    uint h6 = g + m6;
    uint h7 = h + m7;

    w[0] = h0; w[1] = h1; w[2] = h2; w[3] = h3;
    w[4] = h4; w[5] = h5; w[6] = h6; w[7] = h7;
    w[8] = 0x80000000u;
#pragma unroll
    for (int i = 9; i < 15; i++) w[i] = 0;
    w[15] = 256u;
#pragma unroll
    for (int i = 16; i < 64; i++)
        w[i] = s1(w[i-2]) + w[i-7] + s0(w[i-15]) + w[i-16];

    a = 0x6A09E667u; b = 0xBB67AE85u; c = 0x3C6EF372u; d = 0xA54FF53Au;
    e = 0x510E527Fu; f = 0x9B05688Cu; g = 0x1F83D9ABu; h = 0x5BE0CD19u;
#pragma unroll
    for (int i = 0; i < 64; i++) {
        uint t1 = h + S1(e) + Ch(e,f,g) + K[i] + w[i];
        uint t2 = S0(a) + Maj(a,b,c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    h0 = a + 0x6A09E667u;
    h1 = b + 0xBB67AE85u;
    h2 = c + 0x3C6EF372u;
    h3 = d + 0xA54FF53Au;
    h4 = e + 0x510E527Fu;
    h5 = f + 0x9B05688Cu;
    h6 = g + 0x1F83D9ABu;
    h7 = h + 0x5BE0CD19u;

    const uint base = tid * 8u;
    out_digest[base + 0] = h0;
    out_digest[base + 1] = h1;
    out_digest[base + 2] = h2;
    out_digest[base + 3] = h3;
    out_digest[base + 4] = h4;
    out_digest[base + 5] = h5;
    out_digest[base + 6] = h6;
    out_digest[base + 7] = h7;
}
