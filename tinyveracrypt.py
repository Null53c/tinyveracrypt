#! /bin/sh
# by pts@fazekas.hu at Sat Oct 29 19:43:26 CEST 2016

""":" #tinyveracrypt: VeraCrypt-compatible block device encryption setup

type python2.7 >/dev/null 2>&1 && exec python2.7 -- "$0" ${1+"$@"}
type python2.6 >/dev/null 2>&1 && exec python2.6 -- "$0" ${1+"$@"}
type python2.5 >/dev/null 2>&1 && exec python2.5 -- "$0" ${1+"$@"}
type python2.4 >/dev/null 2>&1 && exec python2.4 -- "$0" ${1+"$@"}
exec python -- ${1+"$@"}; exit 1

This script works with Python 2.5, 2.6 and 2.7 out of the box, and with
Python 2.4 if the hashlib is installed from PyPi. It doesn't work with older
versions of Python or Python 3.x.
"""

import binascii
import itertools
import struct
import sys

# --- strxor.

try:
  __import__('Crypto.Util.strxor')
  def make_strxor(size, strxor=sys.modules['Crypto.Util.strxor'].strxor):
    return strxor
except ImportError:
  # This is the naive implementation, it's too slow:
  #
  # def strxor(a, b, izip=itertools.izip):
  #   return ''.join(chr(ord(x) ^ ord(y)) for x, y in izip(a, b))
  #
  # 58 times slower pure Python implementation, see
  # http://stackoverflow.com/a/19512514/97248
  def make_strxor(size):
    def strxor(a, b, izip=itertools.izip, pack=struct.pack, unpack=struct.unpack, fmt='%dB' % size):
      return pack(fmt, *(a ^ b for a, b in izip(unpack(fmt, a), unpack(fmt, b))))
    return strxor



# ---  AES XTS crypto code.
#
# Code based on from CryptoPlus (2014-11-17): https://github.com/doegox/python-cryptoplus/commit/a5a1f8aecce4ddf476b2d80b586822d9e91eeb7d
#
# Uses make_strxor above.
#

class rijndael(object):
    """Helper class used by crypt_aes_xts."""

    # --- Initialize the following constants: [S, Si, T1, T2, T3, T4, T5, T6, T7, T8, U1, U2, U3, U4, num_rounds, rcon, shifts.

    shifts = [[[0, 0], [1, 3], [2, 2], [3, 1]],
              [[0, 0], [1, 5], [2, 4], [3, 3]],
              [[0, 0], [1, 7], [3, 5], [4, 4]]]

    # [keysize][block_size]
    num_rounds = {16: {16: 10, 24: 12, 32: 14}, 24: {16: 12, 24: 12, 32: 14}, 32: {16: 14, 24: 14, 32: 14}}

    A = [[1, 1, 1, 1, 1, 0, 0, 0],
         [0, 1, 1, 1, 1, 1, 0, 0],
         [0, 0, 1, 1, 1, 1, 1, 0],
         [0, 0, 0, 1, 1, 1, 1, 1],
         [1, 0, 0, 0, 1, 1, 1, 1],
         [1, 1, 0, 0, 0, 1, 1, 1],
         [1, 1, 1, 0, 0, 0, 1, 1],
         [1, 1, 1, 1, 0, 0, 0, 1]]

    # produce log and alog tables, needed for multiplying in the
    # field GF(2^m) (generator = 3)
    alog = [1]
    for i in xrange(255):
        j = (alog[-1] << 1) ^ alog[-1]
        if j & 0x100 != 0:
            j ^= 0x11B
        alog.append(j)

    log = [0] * 256
    for i in xrange(1, 255):
        log[alog[i]] = i

    # multiply two elements of GF(2^m)
    def mul(a, b, alog, log):
        if a == 0 or b == 0:
            return 0
        return alog[(log[a & 0xFF] + log[b & 0xFF]) % 255]

    # substitution box based on F^{-1}(x)
    box = [[0] * 8 for i in xrange(256)]
    box[1][7] = 1
    for i in xrange(2, 256):
        j = alog[255 - log[i]]
        for t in xrange(8):
            box[i][t] = (j >> (7 - t)) & 0x01

    B = [0, 1, 1, 0, 0, 0, 1, 1]

    # affine transform:  box[i] <- B + A*box[i]
    cox = [[0] * 8 for i in xrange(256)]
    for i in xrange(256):
        for t in xrange(8):
            cox[i][t] = B[t]
            for j in xrange(8):
                cox[i][t] ^= A[t][j] * box[i][j]

    # S-boxes and inverse S-boxes
    S =  [0] * 256
    Si = [0] * 256
    for i in xrange(256):
        S[i] = cox[i][0] << 7
        for t in xrange(1, 8):
            S[i] ^= cox[i][t] << (7-t)
        Si[S[i] & 0xFF] = i

    # T-boxes
    G = [[2, 1, 1, 3],
        [3, 2, 1, 1],
        [1, 3, 2, 1],
        [1, 1, 3, 2]]

    AA = [[0] * 8 for i in xrange(4)]

    for i in xrange(4):
        for j in xrange(4):
            AA[i][j] = G[i][j]
            AA[i][i+4] = 1

    for i in xrange(4):
        pivot = AA[i][i]
        if pivot == 0:
            t = i + 1
            while AA[t][i] == 0 and t < 4:
                t += 1
                assert t != 4, 'G matrix must be invertible'
                for j in xrange(8):
                    AA[i][j], AA[t][j] = AA[t][j], AA[i][j]
                pivot = AA[i][i]
        for j in xrange(8):
            if AA[i][j] != 0:
                AA[i][j] = alog[(255 + log[AA[i][j] & 0xFF] - log[pivot & 0xFF]) % 255]
        for t in xrange(4):
            if i != t:
                for j in xrange(i+1, 8):
                    AA[t][j] ^= mul(AA[i][j], AA[t][i], alog, log)
                AA[t][i] = 0

    iG = [[0] * 4 for i in xrange(4)]

    for i in xrange(4):
        for j in xrange(4):
            iG[i][j] = AA[i][j + 4]

    def mul4(a, bs, mul, alog, log):
        if a == 0:
            return 0
        r = 0
        for b in bs:
            r <<= 8
            if b != 0:
                r = r | mul(a, b, alog, log)
        return r

    T1 = []
    T2 = []
    T3 = []
    T4 = []
    T5 = []
    T6 = []
    T7 = []
    T8 = []
    U1 = []
    U2 = []
    U3 = []
    U4 = []

    for t in xrange(256):
        s = S[t]
        T1.append(mul4(s, G[0], mul, alog, log))
        T2.append(mul4(s, G[1], mul, alog, log))
        T3.append(mul4(s, G[2], mul, alog, log))
        T4.append(mul4(s, G[3], mul, alog, log))

        s = Si[t]
        T5.append(mul4(s, iG[0], mul, alog, log))
        T6.append(mul4(s, iG[1], mul, alog, log))
        T7.append(mul4(s, iG[2], mul, alog, log))
        T8.append(mul4(s, iG[3], mul, alog, log))

        U1.append(mul4(t, iG[0], mul, alog, log))
        U2.append(mul4(t, iG[1], mul, alog, log))
        U3.append(mul4(t, iG[2], mul, alog, log))
        U4.append(mul4(t, iG[3], mul, alog, log))

    # round constants
    rcon = [1]
    r = 1
    for t in xrange(1, 30):
        r = mul(2, r, alog, log)
        rcon.append(r)

    del A, AA, pivot, B, G, box, log, alog, i, j, r, s, t, mul, mul4, cox, iG


    # --- End of constant initialization.

    def __init__(self, key):
        block_size = 16
        if len(key) != 16 and len(key) != 24 and len(key) != 32:
            raise ValueError('Invalid key size: ' + str(len(key)))
        self.block_size = block_size
        rcon, S, U1, U2, U3, U4 = self.rcon, self.S, self.U1, self.U2, self.U3, self.U4

        ROUNDS = self.num_rounds[len(key)][block_size]
        BC = block_size / 4
        # encryption round keys
        Ke = [[0] * BC for i in xrange(ROUNDS + 1)]
        # decryption round keys
        Kd = [[0] * BC for i in xrange(ROUNDS + 1)]
        ROUND_KEY_COUNT = (ROUNDS + 1) * BC
        KC = len(key) / 4

        # copy user material bytes into temporary ints
        tk = []
        for i in xrange(0, KC):
            tk.append((ord(key[i * 4]) << 24) | (ord(key[i * 4 + 1]) << 16) |
                (ord(key[i * 4 + 2]) << 8) | ord(key[i * 4 + 3]))

        # copy values into round key arrays
        t = 0
        j = 0
        while j < KC and t < ROUND_KEY_COUNT:
            Ke[t / BC][t % BC] = tk[j]
            Kd[ROUNDS - (t / BC)][t % BC] = tk[j]
            j += 1
            t += 1
        tt = 0
        rconpointer = 0
        while t < ROUND_KEY_COUNT:
            # extrapolate using phi (the round key evolution function)
            tt = tk[KC - 1]
            tk[0] ^= (S[(tt >> 16) & 0xFF] & 0xFF) << 24 ^  \
                     (S[(tt >>  8) & 0xFF] & 0xFF) << 16 ^  \
                     (S[ tt        & 0xFF] & 0xFF) <<  8 ^  \
                     (S[(tt >> 24) & 0xFF] & 0xFF)       ^  \
                     (rcon[rconpointer]    & 0xFF) << 24
            rconpointer += 1
            if KC != 8:
                for i in xrange(1, KC):
                    tk[i] ^= tk[i-1]
            else:
                for i in xrange(1, KC / 2):
                    tk[i] ^= tk[i-1]
                tt = tk[KC / 2 - 1]
                tk[KC / 2] ^= (S[ tt        & 0xFF] & 0xFF)       ^ \
                              (S[(tt >>  8) & 0xFF] & 0xFF) <<  8 ^ \
                              (S[(tt >> 16) & 0xFF] & 0xFF) << 16 ^ \
                              (S[(tt >> 24) & 0xFF] & 0xFF) << 24
                for i in xrange(KC / 2 + 1, KC):
                    tk[i] ^= tk[i-1]
            # copy values into round key arrays
            j = 0
            while j < KC and t < ROUND_KEY_COUNT:
                Ke[t / BC][t % BC] = tk[j]
                Kd[ROUNDS - (t / BC)][t % BC] = tk[j]
                j += 1
                t += 1
        # inverse MixColumn where needed
        for r in xrange(1, ROUNDS):
            for j in xrange(BC):
                tt = Kd[r][j]
                Kd[r][j] = U1[(tt >> 24) & 0xFF] ^ \
                           U2[(tt >> 16) & 0xFF] ^ \
                           U3[(tt >>  8) & 0xFF] ^ \
                           U4[ tt        & 0xFF]
        self.Ke = Ke
        self.Kd = Kd

    def encrypt(self, plaintext):
        if len(plaintext) != self.block_size:
            raise ValueError('wrong block length, expected ' + str(self.block_size) + ' got ' + str(len(plaintext)))
        Ke, shifts, S, T1, T2, T3, T4 = self.Ke, self.shifts, self.S, self.T1, self.T2, self.T3, self.T4

        BC = self.block_size / 4
        ROUNDS = len(Ke) - 1
        if BC == 4:
            SC = 0
        elif BC == 6:
            SC = 1
        else:
            SC = 2
        s1 = shifts[SC][1][0]
        s2 = shifts[SC][2][0]
        s3 = shifts[SC][3][0]
        a = [0] * BC
        # temporary work array
        t = []
        # plaintext to ints + key
        for i in xrange(BC):
            t.append((ord(plaintext[i * 4    ]) << 24 |
                      ord(plaintext[i * 4 + 1]) << 16 |
                      ord(plaintext[i * 4 + 2]) <<  8 |
                      ord(plaintext[i * 4 + 3])        ) ^ Ke[0][i])
        # apply round transforms
        for r in xrange(1, ROUNDS):
            for i in xrange(BC):
                a[i] = (T1[(t[ i           ] >> 24) & 0xFF] ^
                        T2[(t[(i + s1) % BC] >> 16) & 0xFF] ^
                        T3[(t[(i + s2) % BC] >>  8) & 0xFF] ^
                        T4[ t[(i + s3) % BC]        & 0xFF]  ) ^ Ke[r][i]
            t = a[:]
        # last round is special
        result = []
        for i in xrange(BC):
            tt = Ke[ROUNDS][i]
            result.append(chr((S[(t[ i           ] >> 24) & 0xFF] ^ (tt >> 24)) & 0xFF))
            result.append(chr((S[(t[(i + s1) % BC] >> 16) & 0xFF] ^ (tt >> 16)) & 0xFF))
            result.append(chr((S[(t[(i + s2) % BC] >>  8) & 0xFF] ^ (tt >>  8)) & 0xFF))
            result.append(chr((S[ t[(i + s3) % BC]        & 0xFF] ^  tt       ) & 0xFF))
        return ''.join(result)

    def decrypt(self, ciphertext):
        if len(ciphertext) != self.block_size:
            raise ValueError('wrong block length, expected ' + str(self.block_size) + ' got ' + str(len(plaintext)))
        Kd, shifts, Si, T5, T6, T7, T8 = self.Kd, self.shifts, self.Si, self.T5, self.T6, self.T7, self.T8

        BC = self.block_size / 4
        ROUNDS = len(Kd) - 1
        if BC == 4:
            SC = 0
        elif BC == 6:
            SC = 1
        else:
            SC = 2
        s1 = shifts[SC][1][1]
        s2 = shifts[SC][2][1]
        s3 = shifts[SC][3][1]
        a = [0] * BC
        # temporary work array
        t = [0] * BC
        # ciphertext to ints + key
        for i in xrange(BC):
            t[i] = (ord(ciphertext[i * 4    ]) << 24 |
                    ord(ciphertext[i * 4 + 1]) << 16 |
                    ord(ciphertext[i * 4 + 2]) <<  8 |
                    ord(ciphertext[i * 4 + 3])        ) ^ Kd[0][i]
        # apply round transforms
        for r in xrange(1, ROUNDS):
            for i in xrange(BC):
                a[i] = (T5[(t[ i           ] >> 24) & 0xFF] ^
                        T6[(t[(i + s1) % BC] >> 16) & 0xFF] ^
                        T7[(t[(i + s2) % BC] >>  8) & 0xFF] ^
                        T8[ t[(i + s3) % BC]        & 0xFF]  ) ^ Kd[r][i]
            t = a[:]
        # last round is special
        result = []
        for i in xrange(BC):
            tt = Kd[ROUNDS][i]
            result.append(chr((Si[(t[ i           ] >> 24) & 0xFF] ^ (tt >> 24)) & 0xFF))
            result.append(chr((Si[(t[(i + s1) % BC] >> 16) & 0xFF] ^ (tt >> 16)) & 0xFF))
            result.append(chr((Si[(t[(i + s2) % BC] >>  8) & 0xFF] ^ (tt >>  8)) & 0xFF))
            result.append(chr((Si[ t[(i + s3) % BC]        & 0xFF] ^  tt       ) & 0xFF))
        return ''.join(result)


strxor_16 = make_strxor(16)


def check_aes_xts_key(aes_xts_key):
  if len(aes_xts_key) != 64:
    raise ValueError('aes_xts_key must be 64 bytes, got: %d' % len(aes_xts_key))


# We use pure Python code (from CryptoPlus) for AES XTS encryption. This is
# slow, but it's not a problem, because we have to encrypt only 512 bytes
# per run. Please note that pycrypto-2.6.1 (released on 2013-10-17) and
# other C crypto libraries with Python bindings don't support AES XTS.
def crypt_aes_xts(aes_xts_key, data, do_encrypt, ofs=0):
  check_aes_xts_key(aes_xts_key)
  if len(data) < 16:
    raise ValueError('At least one block of 128 bits needs to be supplied.')
  if len(data) >> 27:
    raise ValueError('data too long.')  # This is an implementation limitation.
  if ofs:
    if ofs & 15:
      raise ValueError('ofs must be divisible by 16, got: %d' % ofs)
    if ofs < 0:
      raise ValueError('ofs must be nonnegative, got: %d' % ofs)

  # This would work instead of inlining:
  #
  #   import CryptoPlus.Cipher.python_AES
  #   new_aes_xts = lambda aes_xts_key: CryptoPlus.Cipher.python_AES.new((aes_xts_key[0 : 32], aes_xts_key[32 : 64]), CryptoPlus.Cipher.python_AES.MODE_XTS)
  #   cipher = new_aes_xts(aes_xts_key)
  #   if do_encrypt:
  #     return cipher.encrypt(data)
  #   else:
  #     return cipher.decrypt(data)

  do_decrypt = not do_encrypt
  codebook1, codebook2 = rijndael(aes_xts_key[0 : 32]), rijndael(aes_xts_key[32 : 64])
  codebook1_crypt = (codebook1.encrypt, codebook1.decrypt)[do_decrypt]

  # initializing T
  # e_k2_n = E_K2(tweak)
  e_k2_n = codebook2.encrypt('\0' * 16)[::-1]
  T = [int(e_k2_n.encode('hex'), 16)]

  def step(tocrypt):
    T_string = ('%032x' % T[0]).decode('hex')[::-1]
    # C = E_K1(P xor T) xor T
    return strxor_16(T_string, codebook1_crypt(strxor_16(T_string, tocrypt)))

  def T_update():
    # Used for calculating T for a certain step using the T value from the previous step
    T[0] <<= 1
    # if (Cout)
    if T[0] >> (8*16):
      #T[0] ^= GF_128_FDBK;
      T[0] ^= 0x100000000000000000000000000000087

  while ofs:
    T_update()
    ofs -= 16

  output = []
  i=0
  while i < ((len(data) >> 4)-1): #Decrypt all the blocks but one last full block and opt one last partial block
    # C = E_K1(P xor T) xor T
    output.append(step(data[i << 4:(i+1) << 4]))
    # T = E_K2(n) mul (a pow i)
    T_update()
    i+=1

  # Check if the data supplied is a multiple of 16 bytes -> one last full block and we're done
  if len(data[i << 4:]) == 16:
    # C = E_K1(P xor T) xor T
    output.append(step(data[i << 4:(i+1) << 4]))
    # T = E_K2(n) mul (a pow i)
    T_update()
  else:
    T_temp = [T[0]]
    T_update()
    T_temp.append(T[0])
    if do_decrypt:
      # Permutation of the last two indexes
      T_temp.reverse()
    # Decrypt/Encrypt the last two blocks when data is not a multiple of 16 bytes
    Cm1 = data[i << 4:(i+1) << 4]
    Cm = data[(i+1) << 4:]
    T[0] = T_temp[0]
    PP = step(Cm1)
    Cp = PP[len(Cm):]
    Pm = PP[:len(Cm)]
    CC = Cm+Cp
    T[0] = T_temp[1]
    Pm1 = step(CC)
    output.append(Pm1)
    output.append(Pm)
  return ''.join(output)


# ---

# Helpers for do_hmac.
hmac_trans_5C = ''.join(chr(x ^ 0x5C) for x in xrange(256))
hmac_trans_36 = ''.join(chr(x ^ 0x36) for x in xrange(256))


# Faster than `import hmac' because of less indirection.
def do_hmac(key, msg, digest_cons, blocksize):
  outer = digest_cons()
  inner = digest_cons()
  if len(key) > blocksize:
    key = digest_cons(key).digest()
    # Usually inner.digest_size <= blocksize, so now len(key) < blocksize.
  key += '\0' * (blocksize - len(key))
  outer.update(key.translate(hmac_trans_5C))
  inner.update(key.translate(hmac_trans_36))
  inner.update(msg)
  outer.update(inner.digest())
  return outer.digest()


has_sha512_hashlib = has_sha512_openssl_hashlib = False
try:
  __import__('hashlib').sha512
  has_sha512_hashlib = True
  has_sha512_openssl_hashlib = __import__('hashlib').sha512.__name__.startswith('openssl_')
except (ImportError, AttributeError):
  pass
has_sha512_pycrypto = False
try:
  __import__('Crypto.Hash._SHA512')
  has_sha512_pycrypto = True
except ImportError:
  pass
if has_sha512_openssl_hashlib:  # Fastest.
  sha512 = sys.modules['hashlib'].sha512
elif has_sha512_pycrypto:
  # Faster than: Crypto.Hash.SHA512.SHA512Hash
  sha512 = sys.modules['Crypto.Hash._SHA512'].new
elif has_sha512_hashlib:
  sha512 = sys.modules['hashlib'].sha512
else:
  # Using a pure Python implementation here would be too slow, because
  # sha512 is used in pbkdf2.
  raise ImportError('Cannot find SHA512 implementation: install hashlib or pycrypto.')


# Faster than `import pbkdf2' (available on pypi) or `import
# Crypto.Protocol.KDF', because of less indirection.
def pbkdf2(passphrase, salt, size, iterations, digest_cons, blocksize):
  """Computes an binary key from a passphrase using PBKDF2.

  This is deliberately slow (to make dictionary-based attacks on passphrase
  slower), especially when iterations is high.
  """
  # strxor is the slowest operation in pbkdf2. For example, for
  # iterations=500000, digest_cons=sha512, len(passphrase) == 3, calls to
  # strxor take 0.2s with Crypto.Util.strxor.strxor, and 11.6s with the pure
  # Python make_strxor above. Other operations within the pbkdf2 call take
  # about 5.9s if hashlib.sha512 is used, and 12.4s if
  # Crypto.Hash._SHA512.new (also implemented in C) is used.

  _do_hmac = do_hmac
  key, i, k = [], 1, size
  while k > 0:
    u = previousu = _do_hmac(passphrase, salt + struct.pack('>I', i), digest_cons, blocksize)
    _strxor = make_strxor(len(u))
    for j in xrange(iterations - 1):
      previousu = _do_hmac(passphrase, previousu, digest_cons, blocksize)
      u = _strxor(u, previousu)
    key.append(u)
    k -= len(u)
    i += 1
  return ''.join(key)[:size]


try:
  if (has_sha512_openssl_hashlib and
      getattr(__import__('hashlib'), 'pbkdf2_hmac', None)):
    # If pbkdf2_hmac is available (since Python 2.7.8), use it. This is a
    # speedup from 8.8s to 7.0s user time, in addition to openssl_sha512.
    #
    # TODO(pts): Also use https://pypi.python.org/pypi/backports.pbkdf2 , if
    # available and it uses OpenSSL.
    def pbkdf2(passphrase, salt, size, iterations, digest_cons, blocksize):
      # Ignore `blocksize'. It's embedded in hash_name.
      import hashlib
      hash_name = digest_cons.__name__.lower()
      if hash_name.startswith('openssl_'):
        hash_name = hash_name[hash_name.find('_') + 1:]
      return hashlib.pbkdf2_hmac(hash_name, passphrase, salt, iterations, size)
except ImportError:
  pass


def check_decrypted_size(decrypted_size):
  min_decrypted_size = 36 << 10  # Enforced by VeraCrypt.
  if decrypted_size < min_decrypted_size:
    raise ValueError('decrypted_size must be at least %d bytes, got: %d' %
                     (min_decrypted_size, decrypted_size))
  if decrypted_size & 4095:
    raise ValueError('decrypted_size must be divisible by 4096, got: %d' %
                     decrypted_size)


def check_keytable(keytable):
  if len(keytable) != 64:
    raise ValueError('keytable must be 64 bytes, got: %d' % len(keytable))


def check_keytable_or_keytablep(keytable):
  if len(keytable) not in (64, 256):
    raise ValueError('keytable must be 64 or 256 bytes, got: %d' % len(keytable))


def check_header_key(header_key):
  if len(header_key) != 64:
    raise ValueError('header_key must be 64 bytes, got: %d' % len(header_key))


def check_dechd(dechd):
  if len(dechd) != 512:
    raise ValueError('dechd must be 512 bytes, got: %d' % len(dechd))


def check_sector_size(sector_size):
  if sector_size < 512 or sector_size & (sector_size - 1):
    raise ValueError('sector_size must be a power of 2 at least 512: %d' % sector_size)


def check_salt(salt):
  if len(salt) != 64:
    raise ValueError('salt must be 64 bytes, got: %d' % len(salt))


def build_dechd(salt, keytable, decrypted_size, sector_size, decrypted_ofs=None):
  check_keytable_or_keytablep(keytable)
  check_decrypted_size(decrypted_size)
  check_salt(salt)
  check_sector_size(sector_size)
  if decrypted_ofs is None:
    decrypted_ofs = 0x20000
  if decrypted_ofs < 0:
    # The value of 0 works with veracrypt-console.
    # Typical value is 0x20000 for non-hidden volumes.
    raise ValueError('decrypted_size must be nonnegative, got: %d' % decrypted_ofs)
  if decrypted_ofs & 511:
    # TODO(pts): What does aes_xts require as minimum? 16?
    raise ValueError('decrypted_ofs must be a multiple of 512, got: %d' % decrypted_ofs)
  keytablep = keytable + '\0' * (256 - len(keytable))
  keytable = None  # Unused. keytable[:64]
  keytablep_crc32 = ('%08x' % (binascii.crc32(keytablep) & 0xffffffff)).decode('hex')
  # Constants are based on what veracrypt-1.17 generates.
  signature = 'VERA'
  header_format_version = 5
  minimum_version_to_extract = (1, 11)
  hidden_volume_size = 0
  flag_bits = 0
  # https://gitlab.com/cryptsetup/cryptsetup/wikis/TrueCryptOnDiskFormat
  # https://www.veracrypt.fr/en/VeraCrypt%20Volume%20Format%20Specification.html
  # --- 0: VeraCrypt hd sector starts here
  # 0 + 64: salt
  # --- 64: header starts here
  # 64 + 4: signature: "VERA": 56455241
  # 68 + 2: header_format_version: Volume header format version: 0005
  # 70 + 2: minimum_version_to_extract: Minimum program version to open (1.11): 010b
  # 72 + 4: keytablep_crc32: CRC-32 of the keytable + keytablep (decrypted bytes 256..511): ????????
  # 76 + 16: zeros16: 00000000000000000000000000000000
  # 92 + 8: hidden_volume_size: size of hidden volume (0 for non-hidden): 0000000000000000
  # 100 + 8: decrypted_size: size of decrypted volume: ????????????????
  # 108 + 8: decrypted_ofs: offset of encrypted area from 0 (beginning of salt), i.e. byte offset of the master key scope (typically 0x20000): 0000000000020000
  # 116 + 8: decrypted_size_b: size of the encrypted area within the master key scope (same as size of the decrypted volume): ????????????????
  # 124 + 4: flag_bits: flag bits (0): 00000000
  # 128 + 4: sector_size: sector size (512 -- shouldn't it be 4096?): 00000200
  # 132 + 120: zeros120: 00..00
  # --- 252: header ends here
  # 252 + 4: header_crc32: CRC-32 of header
  # 256 + 64: keytable (used as key by `dmsetup table' after hex-encoding)
  # 320 + 192: keytable_padding: typically zeros, but can be anything: 00..00
  # --- 512: VeraCrypt hd sector ends here
  #
  # We can overlap this header with FAT12 and FAT16. FAT12 and FAT16
  # filesystem headers fit into our salt. See 'mkinfat'.
  #
  # We can't overlap this header with XFS (e.g. set_xfs_id.py), because XFS
  # filesystem headers conflict with this header (decrypted_size vs
  # xfs.sectsize, byte_offset_for_key vs xfs.label, sector_size vs
  # xfs.icount, flag_bits vs xfs.blocklog etc.).
  header = struct.pack(
      '>4sHBB4s16xQQQQLL120x', signature, header_format_version,
      minimum_version_to_extract[0], minimum_version_to_extract[1],
      keytablep_crc32, hidden_volume_size, decrypted_size,
      decrypted_ofs, decrypted_size, flag_bits, sector_size)
  assert len(header) == 188
  header_crc32 = ('%08x' % (binascii.crc32(header) & 0xffffffff)).decode('hex')
  dechd = ''.join((salt, header, header_crc32, keytablep))
  assert len(dechd) == 512
  return dechd


def check_full_dechd(dechd, enchd_suffix_size=0):
  """Does a full, after-decryption check on dechd.

  This is also used for passphrase: on a wrong passphrase, dechd is 512
  bytes of garbage.

  The checks here are more strict than what `cryptsetup' or the mount
  operation of `veracrypt' does. They can be relaxed if the need arises.
  """
  check_dechd(dechd)
  if enchd_suffix_size > 192:
    raise ValueError('enchd_suffix_size too large, got: %s' % enchd_suffix_size)
  if dechd[64 : 64 + 4] != 'VERA':  # Or 'TRUE'.
    raise ValueError('Magic mismatch.')
  if dechd[72 : 76] != ('%08x' % (binascii.crc32(dechd[256 : 512]) & 0xffffffff)).decode('hex'):
    raise ValueError('keytablep_crc32 mismatch.')
  if dechd[252 : 256] != ('%08x' % (binascii.crc32(dechd[64 : 252]) & 0xffffffff)).decode('hex'):
    raise ValueError('header_crc32 mismatch.')
  header_format_version, = struct.unpack('>H', dechd[68 : 68 + 2])
  if not (5 <= header_format_version <= 9):
    raise ValueError('header_format_version mismatch.')
  minimum_version_to_extract = struct.unpack('>BB', dechd[70 : 70 + 2])
  if minimum_version_to_extract != (1, 11):
    raise ValueError('minimum_version_to_extract mismatch.')
  if dechd[76 : 76 + 16].lstrip('\0'):
    raise ValueError('Missing NUL padding at 76.')
  hidden_volume_size, = struct.unpack('>Q', dechd[92 : 92 + 8])
  if hidden_volume_size:
    # Hidden volume detected here, but currently this tool doesn't support
    # hidden volumes.
    raise ValueError('Unexpected hidden volume.')
  decrypted_size, = struct.unpack('>Q', dechd[100 : 100 + 8])
  if decrypted_size >> 50:  # Larger than 1 PB is insecure.
    raise ValueError('Volume too large.')
  decrypted_ofs, = struct.unpack('>Q', dechd[108 : 108 + 8])
  encrypted_area_size, = struct.unpack('>Q', dechd[116 : 116 + 8])
  if encrypted_area_size != decrypted_size:
    raise ValueError('encrypted_area_size mismatch.')
  flag_bits, = struct.unpack('>L', dechd[124 : 124 + 4])
  if flag_bits:
    raise ValueError('flag_bits mismatch.')
  sector_size, = struct.unpack('>L', dechd[128 : 128 + 4])
  check_sector_size(sector_size)
  if dechd[132 : 132 + 120].lstrip('\0'):
    # Does actual VeraCrypt check this? Does cryptsetup --veracrypt check this?
    raise ValueError('Missing NUL padding at 132.')
  if dechd[256 + 64 : 512 - ((enchd_suffix_size + 15) & ~15)].lstrip('\0'):
    # Does actual VeraCrypt check this? Does cryptsetup --veracrypt check this?
    raise ValueError('Missing NUL padding after keytable.')


def build_table(keytable, decrypted_size, decrypted_ofs, raw_device):
  check_keytable(keytable)
  check_decrypted_size(decrypted_size)
  if isinstance(raw_device, (list, tuple)):
    raw_device = '%d:%s' % tuple(raw_device)
  cipher = 'aes-xts-plain64'
  iv_offset = offset = decrypted_ofs
  start_offset_on_logical = 0
  opt_params = ('allow_discards',)
  if opt_params:
    opt_params_str = ' %d %s' % (len(opt_params), ' '.join(opt_params))
  else:
    opt_params_str = ''
  # https://www.kernel.org/doc/Documentation/device-mapper/dm-crypt.txt
  return '%d %d crypt %s %s %d %s %s%s\n' % (
      start_offset_on_logical, decrypted_size >> 9,
      cipher, keytable.encode('hex'),
      iv_offset >> 9, raw_device, offset >> 9, opt_params_str)


def encrypt_header(dechd, header_key):
  check_dechd(dechd)
  check_header_key(header_key)
  enchd = dechd[:64] + crypt_aes_xts(header_key, dechd[64 : 512], do_encrypt=True)
  assert len(enchd) == 512
  return enchd


def decrypt_header(enchd, header_key):
  if len(enchd) != 512:
    raise ValueError('enchd must be 512 bytes, got: %d' % len(enchd))
  check_header_key(header_key)
  dechd = enchd[:64] + crypt_aes_xts(header_key, enchd[64 : 512], do_encrypt=False)
  assert len(dechd) == 512
  return dechd


# Slow, takes about 6..60 seconds.
def build_header_key(passphrase, salt_or_enchd, pim=None):
  if len(salt_or_enchd) < 64:
    raise ValueError('Salt too short.')
  salt = salt_or_enchd[:64]
  # Speedup for testing.
  if passphrase == 'ThisIsMyVeryLongPassphraseForMyVeraCryptVolume':
    if salt == "~\xe2\xb7\xa1M\xf2\xf6b,o\\%\x08\x12\xc6'\xa1\x8e\xe9Xh\xf2\xdd\xce&\x9dd\xc3\xf3\xacx^\x88.\xe8\x1a6\xd1\xceg\xebA\xbc]A\x971\x101\x163\xac(\xafs\xcbF\x19F\x15\xcdG\xc6\xb3":
      return '\x11Q\x91\xc5h%\xb2\xb2\xf0\xed\x1e\xaf\x12C6V\x7f+\x89"<\'\xd5N\xa2\xdf\x03\xc0L~G\xa6\xc9/\x7f?\xbd\x94b:\x91\x96}1\x15\x12\xf7\xc6g{Rkv\x86Av\x03\x16\n\xf8p\xc2\xa33'
    elif salt == '\xeb<\x90mkfs.fat\0\x02\x01\x01\0\x01\x10\0\0\x01\xf8\x01\x00 \x00@\0\0\0\0\0\0\0\0\0\x80\x00)\xe3\xbe\xad\xdeminifat3   FAT12   \x0e\x1f':
      return '\xa3\xafQ\x1e\xcb\xb7\x1cB`\xdb\x8aW\xeb0P\xffSu}\x9c\x16\xea-\xc2\xb7\xc6\xef\xe3\x0b\xdbnJ"\xfe\x8b\xb3c=\x16\x1ds\xc2$d\xdf\x18\xf3F>\x8e\x9d\n\xda\\\x8fHk?\x9d\xe8\x02 \xcaF'
    elif salt == '\xeb<\x90mkfs.fat\x00\x02\x01\x01\x00\x01\x10\x00\x00\x01\xf8\x01\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00)\xe3\xbe\xad\xdeminifat3   FAT12   \x0e\x1f':
      return '\xb8\xe0\x11d\xfa!\x1c\xb6\xf8\xb9\x03\x05\xff\x8f\x82\x86\xcb,B\xa4\xe2\xfc,:Y2;\xbf\xc2Go\xc7n\x91\xad\xeeq\x10\x00:\x17X~st\x86\x95\nu\xdf\x0c\xbb\x9b\x02\xd7\xe8\xa6\x1d\xed\x91\x05#\x17,'
  if not pim:  # !! Configure it with coomand-line flage --pim=485.
    # --pim=485 corresponds to iterations=500000
    # (https://www.veracrypt.fr/en/Header%20Key%20Derivation.html says that
    # for --hash=sha512 iterations == 15000 + 1000 * pim).
    iterations = 500000
  else:
    iterations = 15000 + 1000 * pim
  # We could use a different hash algorithm and a different iteration count.
  header_key_size = 64
  #blocksize = 16  # For MD2
  #blocksize = 64  # For MD4, MD5, RIPEMD, SHA1, SHA224, SHA256.
  #blocksize = 128  # For SHA384, SHA512.
  sha512_blocksize = 128
  # TODO(pts): Is kernel-mode crypto (AF_ALG,
  # https://www.kernel.org/doc/html/v4.16/crypto/userspace-if.html) faster?
  # cryptsetup seems to be doing it.
  return pbkdf2(passphrase, salt, header_key_size, iterations, sha512, sha512_blocksize)


def parse_dechd(dechd):
  check_dechd(dechd)
  keytable = dechd[256 : 256 + 64]
  decrypted_size, decrypted_ofs = struct.unpack('>QQ', buffer(dechd, 100, 16))
  return keytable, decrypted_size, decrypted_ofs


def get_table(device, passphrase, raw_device):
  enchd = open(device).read(512)
  if len(enchd) != 512:
    raise ValueError('Raw device too short for VeraCrypt header.')
  header_key = build_header_key(passphrase, enchd)  # Slow.
  dechd = decrypt_header(enchd, header_key)
  try:
    check_full_dechd(dechd, enchd_suffix_size=2)
  except ValueError, e:
    # We may put str(e) to the debug log, if requested.
    raise ValueError('Incorrect passphrase (%s).' % e)
  keytable, decrypted_size, decrypted_ofs = parse_dechd(dechd)
  return build_table(keytable, decrypted_size, decrypted_ofs, raw_device)


def get_random_bytes(size, _functions=[]):
  if size == 0:
    return ''
  if not _functions:
    def manual_random(size):
      return ''.join(chr(random.randrange(0, 255)) for _ in xrange(size))

    try:
      import os
      data = os.urandom(1)
      if len(data) != 1:
        raise ValueError
      _functions.append(os.urandom)
    except (ImportError, AttributeError, TypeError, ValueError, OSError):
      _functions.append(manual_random)

  return _functions[0](size)


def build_veracrypt_header(decrypted_size, passphrase, enchd_prefix='', enchd_suffix='', decrypted_ofs=None):
  """Returns 512 bytes.

  Args:
    decrypted_size: Size of the decrypted block device, this is 0x20000
        bytes smaller than the encrypted block device.
  """
  if len(enchd_prefix) > 64:
    raise ValueError('enchd_prefix too long, got: %d' % len(enchd_prefix))
  if len(enchd_suffix) > 192:
    raise ValueError('enchd_suffix too long, got: %d' % len(enchd_suffix))
  if decrypted_size < 512:
    raise ValueError('encrypted_size too small, got: %d' % decrypted_size)
  salt = enchd_prefix + get_random_bytes(64 - len(enchd_prefix))
  header_key = build_header_key(passphrase, salt)  # Slow.
  keytable = get_random_bytes(64)
  sector_size = 512
  dechd = build_dechd(salt, keytable, decrypted_size, sector_size, decrypted_ofs=decrypted_ofs)
  assert len(dechd) == 512
  check_full_dechd(dechd)
  enchd = encrypt_header(dechd, header_key)
  assert len(enchd) == 512
  do_reenc = not enchd.endswith(enchd_suffix)
  if do_reenc:
    keytablep_enc = enchd[256 : -len(enchd_suffix)] + enchd_suffix
    assert keytablep_enc.endswith(enchd_suffix)
    keytablep = crypt_aes_xts(header_key, keytablep_enc, do_encrypt=False, ofs=192)
    assert crypt_aes_xts(header_key, keytablep, do_encrypt=True, ofs=192) == keytablep_enc
    dechd2 = build_dechd(salt, keytablep, decrypted_size, sector_size, decrypted_ofs=decrypted_ofs)
    check_full_dechd(dechd2, len(enchd_suffix))
    assert dechd2.endswith(keytablep)
    assert len(dechd2) == 512
    enchd = encrypt_header(dechd2, header_key)
    assert len(enchd) == 512
    assert enchd.endswith(keytablep_enc)
    assert enchd.endswith(enchd_suffix)
    dechd = dechd2
  assert decrypt_header(enchd, header_key) == dechd
  return enchd


def get_fat_sizes(fat_header):
  import struct
  if len(fat_header) < 64:
    raise ValueError('FAT header shorter than 64 bytes, got: %d' % len(fat_header))
  data = fat_header
  # jmp2, code0, code1 can be random.
  # oem_id, folume label and fstype ares space-padded.
  (jmp0, jmp1, jmp2, oem_id, sector_size, sectors_per_cluster,
   reserved_sector_count, fat_count, rootdir_entry_count, sector_count1,
   media_descriptor, sectors_per_fat, sectors_per_track, heads, hidden_count,
   sector_count, drive_number, bpb_signature, uuid_bin, label, fstype,
   code0, code1,
  ) = struct.unpack('<3B8sHBHBHHBHHHLLHB4s11s8s2B', data[:64])
  # uuid_bin is also serial number.
  if (sector_count1 == 0 and
      reserved_sector_count > 1 and  # fsinfo sector. Typically 32.
      rootdir_entry_count == 0 and
      sectors_per_fat == 0):
    # Also: data[82 : 90] in ('', 'FAT32   ', 'MSWIN4.0', 'MSWIN4.1').
    # FAT32 is not supported because it has more than 64 bytes of filesystem
    # headers.
    raise ValueError('FAT32 detected, but it is not supported.')
  if sector_count1:
    sector_count = sector_count1
  fstype = fstype.rstrip(' ')
  del sector_count1
  #assert 0, sorted((k, v) for k, v in locals().iteritems() if k not in ('data', 'struct'))
  if fstype not in ('FAT12', 'FAT16'):
    raise ValueError('Expected FAT12 or FAT16 filesystem, got: %r' % fstype)
  if hidden_count != 0:
    raise ValueError('Expected hidden_count=0, got: %d' % hidden_count)
  if bpb_signature != 41:
    raise ValueError('Expected bpb_signature=41, got: %d' % bpb_signature)
  if reserved_sector_count < 1:
    raise ValueError('Expected reserved_sector_count>0, got: %d' % reserved_sector_count)
  if rootdir_entry_count <= 0:
    raise ValueError('Expected rootdir_entry_count>0, got: %d' % rootdir_entry_count)
  if sectors_per_fat <= 0:
    raise ValueError('Expected sectors_per_fat>0, got: %d' % sectors_per_fat)
  if fat_count not in (1, 2):
    raise ValueError('Expected fat_count 1 or 2, got: %d' % fat_count)
  rootdir_sector_count = (rootdir_entry_count + ((sector_size >> 5) - 1)) / (sector_size >> 5)
  header_sector_count = reserved_sector_count + sectors_per_fat * fat_count + rootdir_sector_count
  if header_sector_count > sector_count:
    raise ValueError('Too few sectors in FAT filesystem, not even header sectors fit.')
  fatfs_size, fat_count, fat_size, rootdir_size, reserved_size = sector_count * sector_size, fat_count, sectors_per_fat * sector_size, rootdir_sector_count * sector_size, reserved_sector_count * sector_size
  return fatfs_size, fat_count, fat_size, rootdir_size, reserved_size, fstype


def recommend_fat_parameters(fd_sector_count, fat_count, fstype=None, sectors_per_cluster=None):
  """fd_sector_count is sector count for FAT and data together."""
  # * A full FAT12 is: 12 512-byte sectors, 6144 bytes, 6120 used bytes, 4080 entries, 2 dummy entries followed by 4078 cluster entries, smallest value 2, largest value 4079 == 0xfef.
  #   Thus cluster_count <= 4078.
  #   Largest data size with cluster_size=512: 2087936 bytes.  dd if=/dev/zero bs=512 count=4092 of=minifat6.img && mkfs.vfat -f 1 -F 12 -i deadbee6 -n minifat6 -r 16 -s 1 minifat6.img
  #   Largest data size with cluster_size=1024: 4175872 bytes. Doing this with FAT16 cluster_size=512 would add 10240 bytes of overheader.
  #   Largest data size with cluster_size=2048: 8351744 bytes.
  #   Largest data size with cluster_size=4096: 16703488 bytes.
  # * A full FAT16 is: 256 512-byte sectors, 131072 bytes, 131040 used bytes, 65520 entries, 2 dummy entries followed by 65518 cluster entries, smallest value 2, largest value 65519 == 0xffef.
  #   Thus cluster_count <= 65518.
  #   Largest data size with cluster_size=512: 33545216 bytes (<32 MiB).  dd if=/dev/zero bs=512 count=65776 of=minifat7.img && mkfs.vfat -f 1 -F 16 -i deadbee7 -n minifat7 -r 16 -s 1 minifat7.img
  #   Largest data size with cluster_size=65536: 4293787648 bytes (<4 GiB).
  #assert 0, (fstype, sectors_per_cluster)
  if fstype is None:
    fstypes = ('FAT12', 'FAT16')
  if sectors_per_cluster is None:
    sectors_per_clusters = (1, 2, 4, 8, 16, 32, 64, 128)
  options = []
  for fstype in fstypes:
    max_cluster_count = (65518, 4078)[fstype == 'FAT12']
    # Minimum number of clusters for FAT16 is 4087 (based on:
    # https://github.com/Distrotech/mtools/blob/13058eb225d3e804c8c29a9930df0e414e75b18f/mformat.c#L222).
    # Otherwise Linux 3.13 vfat fileystem and `mtools -i mdir' both get
    # confused and assume that the filesystem is FAT12.
    min_cluster_count = (4087, 1)[fstype == 'FAT12']
    for sectors_per_cluster in sectors_per_clusters:
      if sectors_per_cluster > 2 and fstype == 'FAT12':
        continue  # Heuristic, use FAT16 instead.
      # 1 is our lower bound for fat_sector_count.
      cluster_count = (fd_sector_count - 1) / sectors_per_cluster
      while cluster_count > 0:
        if fstype == 'FAT12':
          sectors_per_fat = ((((2 + cluster_count) * 3 + 1) >> 1) + 511) >> 9
        else:
          sectors_per_fat = ((2 + (cluster_count << 1)) + 511) >> 9
        cluster_count2 = (fd_sector_count - sectors_per_fat * fat_count) / sectors_per_cluster
        if cluster_count == cluster_count2:
          break
        cluster_count = cluster_count2
      is_wasted = cluster_count - max_cluster_count > 9
      cluster_count = min(cluster_count, max_cluster_count)
      if cluster_count < min_cluster_count:
        continue
      use_data_sector_count = cluster_count * sectors_per_cluster
      use_fd_sector_count = sectors_per_fat * fat_count + use_data_sector_count
      options.append((-use_fd_sector_count, sectors_per_cluster, fstype, use_fd_sector_count, sectors_per_fat, is_wasted))
  if not options:
    raise ValueError('FAT filesystem would be too small.')
  _, sectors_per_cluster, fstype, use_fd_sector_count, sectors_per_fat, is_wasted = min(options)
  if is_wasted:
    # Typical limits: FAT12 ~2 MiB, FAT16 ~4 GiB.
    raise ValueError('FAT filesystem cannot be that large.')
  #assert 0, (fstype, sectors_per_cluster, use_fd_sector_count, sectors_per_fat)
  return fstype, sectors_per_cluster, use_fd_sector_count, sectors_per_fat


def build_fat_header(label, uuid, fatfs_size, fat_count=None, rootdir_entry_count=None, fstype=None, cluster_size=None):
  """Builds a 64-byte header for a FAT12 or FAT16 filesystem."""
  import struct
  if label is not None:
    label = label.strip()
    if len(label) > 11:
      raise ValueEror('label longer than 11, got: %d' % len(label))
    if label == 'NO NAME':
      label = None
  if label:
    label += ' ' * (11 - len(label))
  else:
    label = None
  if uuid is None:
    uuid_bin = get_random_bytes(4)
  else:
    uuid = uuid.replace('-', '').lower()
    try:
      uuid_bin = uuid.decode('hex')[::-1]
    except TypeError:
      raise ValueError('uuid must be hex, got: %s' % uuid)
  if len(uuid_bin) != 4:
    raise ValueError('uuid_bin must be 4 bytes, got: %s' % len(uuid_bin))
  if fat_count is None:
    fat_count = 1
  else:
    fat_count = int(fat_count)
  if fat_count not in (1, 2):
    raise ValueError('Expected fat_count 1 or 2, got: %d' % fat_count)
  if fatfs_size < 2048:
    raise ValueError('fatfs_size must be at least 2048, got: %d' % fatfs_size)
  if fatfs_size & 511:
    raise ValueError('fatfs_size must be a multiple of 512, got: %d' % fatfs_size)
  if rootdir_entry_count is None:
    rootdir_entry_count = 1  # !! Better default for larger filesystems.
  if rootdir_entry_count <= 0:
    raise ValueError('rootdir_entry_count must be at least 1, got: %d' % rootdir_entry_count)
  if fstype is not None:
    fstype = fstype.upper()
    if fstype not in ('FAT12', 'FAT16'):
      raise ValueError('fstype must be FAT12 or FAT16, got: %r' % (fstype,))
  if cluster_size is None:
    sectors_per_cluster = None
  else:
    sectors_per_cluster = int(cluster_size) >> 9
    if sectors_per_cluster not in (1, 2, 4, 8, 16, 32, 64, 128):
      raise ValueError('cluster_size must be a power of 2: 512 ... 65536, got: %d' % cluster_size)
    cluster_size = None

  sector_size = 512
  sector_count = fatfs_size >> 9
  rootdir_entry_count = (rootdir_entry_count + 15) & ~15  # Round up.
  rootdir_sector_count = (rootdir_entry_count + ((sector_size >> 5) - 1)) / (sector_size >> 5)
  reserved_sector_count = 1  # Only the boot sector (containing fat_header).
  fd_sector_count = sector_count - reserved_sector_count - rootdir_sector_count
  fstype, sectors_per_cluster, fd_sector_count, sectors_per_fat = recommend_fat_parameters(
      fd_sector_count, fat_count, fstype, sectors_per_cluster)
  sector_count = fd_sector_count + reserved_sector_count + rootdir_sector_count
  jmp0, jmp1, jmp2 = 0xeb, 0x3c, 0x90
  oem_id = 'mkfs.fat'
  media_descriptor = 0xf8
  sectors_per_track = 1  # Was 32. 0 indicates LBA, mtools doesn't support it.
  heads = 1  # Was 64. 0 indicates LBA, mtools doesn't support it.
  hidden_count = 0
  drive_number = 0x80
  bpb_signature = 0x29
  code0, code1 = 0x0e, 0x1f
  header_sector_count = reserved_sector_count + sectors_per_fat * fat_count + rootdir_sector_count
  cluster_count = ((fatfs_size >> 9) - header_sector_count) / sectors_per_cluster
  free_size = (cluster_count * sectors_per_cluster) << 9
  if header_sector_count > sector_count:
    raise ValueError(
        'Too few sectors in FAT filesystem, not even header sectors fit, increase fatfs_size to at least %d, got: %d' %
        (header_sector_count << 9, fatfs_size))
  fstype += ' ' * (8 - len(fstype))
  if sector_count >> 16:
    sector_count1 = 0
  else:
    sector_count1, sector_count = sector_count, 0
  fat_header = struct.pack(
      '<3B8sHBHBHHBHHHLLHB4s11s8s2B',
      jmp0, jmp1, jmp2, oem_id, sector_size, sectors_per_cluster,
      reserved_sector_count, fat_count, rootdir_entry_count, sector_count1,
      media_descriptor, sectors_per_fat, sectors_per_track, heads,
      hidden_count, sector_count, drive_number, bpb_signature, uuid_bin, label,
      fstype, code0, code1)
  assert len(fat_header) == 64
  assert label is None or len(label) == 11
  return fat_header, label


def build_veracrypt_fat(decrypted_size, passphrase, fat_header=None, do_include_all_header_sectors=False, device_size=None, **kwargs):
  # FAT12 filesystem header based on minifat3.
  # dd if=/dev/zero bs=1K   count=64  of=minifat1.img && mkfs.vfat -f 1 -F 12 -i deadbeef -n minifat1 -r 16 -s 1 minifat1.img  # 64 KiB FAT12.
  # dd if=/dev/zero bs=512  count=342 of=minifat2.img && mkfs.vfat -f 1 -F 12 -i deadbee2 -n minifat2 -r 16 -s 1 minifat2.img  # Largest FAT12 with 1536 bytes of overhead.
  # dd if=/dev/zero bs=1024 count=128 of=minifat3.img && mkfs.vfat -f 1 -F 12 -i deadbee3 -n minifat3 -r 16 -s 1 minifat3.img  # 128 KiB FAT12.
  # dd if=/dev/zero bs=1K  count=2052 of=minifat5.img && mkfs.vfat -f 1 -F 16 -i deadbee5 -n minifat5 -r 16 -s 1 minifat5.img  # 2052 KiB FAT16.
  # TODO(pts): Have sectors_per_track == 1 to avoid Total number of sectors (342) not a multiple of sectors per track (32)!: `MTOOLS_SKIP_CHECK=1 mtools -c mdir -i minifat2.img'
  #            Use 0 for sectors_per_track and heads.
  # !! TODO(pts): (>=4096) WARNING: Not enough clusters for a 16 bit FAT! The filesystem will be misinterpreted as having a 12 bit FAT without mount option "fat=16".
  if fat_header is None:
    if 'fatfs_size' not in kwargs:
      if (not isinstance(device_size, (int, long)) or
          not isinstance(decrypted_size, (int, long))):
        raise ValueError('Could not infer fatfs_size, missing device_size or decrypted_size.')
      kwargs['fatfs_size'] = device_size - decrypted_size
    fat_header, label = build_fat_header(**kwargs)
  elif kwargs:
    raise ValueError('Both fat_header and FAT parameters (%s) specified.' % sorted(kwargs))
  else:
    label = None
  if len(fat_header) != 64:
    raise ValueError('fat_header must be 64 bytes, got: %d' % len(fat_header))
  # !! Specify UUID and label (minifat3).
  fatfs_size, fat_count, fat_size, rootdir_size, reserved_size, fstype = get_fat_sizes(fat_header)
  if decrypted_size is None:
    if not isinstance(device_size, (int, long)):
      raise TypeError
    decrypted_size = device_size - fatfs_size
    if decrypted_size < 512:
      raise ValueError('FAT filesystem too large, no room for encrypted volume after it.')
  if device_size is not None:
    if decrypted_size != device_size - fatfs_size:
      raise ValueError('Inconsistent device_size, decrypted_size and fatfs_size.')
    device_size = None
  # !! TODO(pts): Randomize same fields in the fat_header (jmp0 = '\xe9', jmp1, jmp2, oem_id only base64, code0, code1) as salt.
  enchd = build_veracrypt_header(
      decrypted_size=decrypted_size, passphrase=passphrase,
      enchd_prefix=fat_header, enchd_suffix='\x55\xaa',
      decrypted_ofs=fatfs_size)
  assert len(enchd) == 512
  assert enchd.startswith(fat_header)
  if not do_include_all_header_sectors:
    return enchd, fatfs_size
  output = [enchd]
  output.append('\0' * (reserved_size - 512))
  if fstype == 'FAT12':
    empty_fat = '\xf8\xff\xff' + '\0' * (fat_size - 3)
  elif fstype == 'FAT16':
    empty_fat = '\xf8\xff\xff\xff' + '\0' * (fat_size - 4)
  else:
    assert 0, 'Unknown fstype: %s' % (fstype,)
  output.extend(empty_fat for _ in xrange(fat_count))
  if label:
    # Volume label in root directory.
    output.append(label)
    output.append('\x08\0\0\xa7|\x8fM\x8fM\0\0\xa7|\x8fM\0\0\0\0\0\0')
    # Rest of root directory.
    output.append('\0' * (rootdir_size - 32))
  else:
    output.append('\0' * rootdir_size)
  data = ''.join(output)
  assert len(data) == reserved_size + fat_size * fat_count + rootdir_size
  assert len(data) <= fatfs_size
  return data, fatfs_size


def main(argv):
  passphrase = 'ThisIsMyVeryLongPassphraseForMyVeraCryptVolume'
  # !! Experiment with decrypted_ofs=0, encrypted ext2 (first 0x400 bytes are arbitrary) or reiserfs/ btrfs (first 0x10000 bytes are arbitrary) filesystem,
  #    Can we have a fake non-FAT filesystem with UUID and label? For reiserfs, set_jfs_id.py would work.
  #    set_xfs_id.py doesn't work, because XFS and VeraCrypt headers conflict.
  #    LUKS (luks.c) can work, but it has UUID only (no label).
  #    No other good filesystem for ext2, see https://github.com/pts/pts-setfsid/blob/master/README.txt
  #    Maybe with bad blocks: bad block 64, and use jfs.
  #    Needs more checking, is it block 32 for jfs? mkfs.ext4 -b 1024 -l badblocks.lst ext4.img
  #    mkfs.reiserfs overwrites the first 0x10000 bytes with '\0', but then we can change it back: perl -e 'print "b"x(1<<16)' | dd bs=64K of=ext4.img conv=notrunc
  #    0x10	Has reserved GDT blocks for filesystem expansion (COMPAT_RESIZE_INODE). Requires RO_COMPAT_SPARSE_SUPER.
  #    $ python -c 'open("bigext4.img", "wb").truncate(8 << 30)'
  #    $ mkfs.ext4 -b 1024 -E nodiscard -F bigext4.img
  #    $ dumpe2fs bigext4.img >bigext4.dump
  #    Primary superblock at 1, Group descriptors at 2-33
  #    Reserved GDT blocks at 34-289  # Always 256, even for smaller filesystems.
  #    $ mkfs.ext4 -b 1024 -E nodiscard -l badblocks.lst -F bigext4.img
  #    Block 32 in primary superblock/group descriptor area bad.
  #    Blocks 1 through 34 must be good in order to build a filesystem.
  #    (So marking block 32 bad won't work for ext2, ext3, ext4 filesystems of at least about 8 GiB in size.)
  if len(argv) < 2:
    print >>sys.stderr, 'fatal: missing command'
    sys.exit(1)
  if len(argv) > 2 and argv[1] == 'get_table':
    # !! Also add mount with compatible syntax.
    # * veracrypt --mount --keyfiles= --protect-hidden=no --pim=485 --filesystem=none --hash=sha512 --encryption=aes  # Creates /dev/mapper/veracrypt1
    # * cryptsetup open /dev/sdb e4t --type tcrypt --veracrypt NAME  # Creates /dev/mapper/NAME
    # Please note that this command is not able to mount all volumes: it
    # works only with hash sha512 and encryption aes-xts-plain64, the
    # default for veracrypt-1.17, and the one the commands mkveracrypt,
    # mkinfat and mkfat generate.
    # !! Autodetect possible number of iterations. See tcrypt_kdf in https://gitlab.com/cryptsetup/cryptsetup/blob/master/lib/tcrypt/tcrypt.c
    # !! Reuse smaller number of iterations when computing bigger.
    device = argv[2]
    #raw_device = '7:0'
    raw_device = device
    sys.stdout.write(get_table(device, passphrase, raw_device))
    sys.stdout.flush()
  elif argv[1] == 'mkveracrypt':
    # TODO(pts): Create the backup header at the end of the device by
    # default, according to:
    # https://www.veracrypt.fr/en/VeraCrypt%20Volume%20Format%20Specification.html
    # 256 KiB smaller than the raw device: VeraCrypt header (64 KiB), hidden volume header (64 KiB), encrypted volume data, backup header (64 KiB), backup hidden volume header (64 KiB)
    device = argv[2]
    f = open(device, 'rb')
    try:
      f.seek(0, 2)
      device_size = f.tell()
    finally:
      f.close()
    decrypted_size = None  # 1 << 20  # !! Make it configurable in the command line, default should be autodetect (None).
    decrypted_ofs = 0x20000  # !! Add command-line flag.
    #decrypted_ofs = 0  # This also works with veracrypt-console on Linux.
    # TODO(pts): Use a randomly generated salt by default.
    salt = "~\xe2\xb7\xa1M\xf2\xf6b,o\\%\x08\x12\xc6'\xa1\x8e\xe9Xh\xf2\xdd\xce&\x9dd\xc3\xf3\xacx^\x88.\xe8\x1a6\xd1\xceg\xebA\xbc]A\x971\x101\x163\xac(\xafs\xcbF\x19F\x15\xcdG\xc6\xb3"
    enchd = build_veracrypt_header(
        decrypted_size=device_size - decrypted_ofs, passphrase=passphrase, decrypted_ofs=decrypted_ofs, enchd_prefix=salt)
    assert len(enchd) == 512
    f = open(device, 'rb+')
    try:
      f.write(enchd)
    finally:
      f.close()
  elif len(argv) > 2 and argv[1] == 'mkinfat':  # Create an encrypted volume after after an existing FAT12 or FAT16 filesystem.
    device = argv[2]
    f = open(device, 'rb')
    try:
      fat_header = f.read(64)
      f.seek(0, 2)
      device_size = f.tell()
    finally:
      f.close()
    decrypted_size = None  # 1 << 20  # !! Make it configurable in the command line, default should be autodetect (None).
    enchd, fatfs_size = build_veracrypt_fat(
        decrypted_size=decrypted_size, passphrase=passphrase, fat_header=fat_header, device_size=device_size)
    assert len(enchd) == 512
    f = open(device, 'rb+')
    try:
      f.write(enchd)
    finally:
      f.close()
  elif len(argv) > 2 and argv[1] == 'mkfat':
    device = argv[2]
    decrypted_size = 1 << 20  # !! Make it configurable in the command line.
    fatfs_size = 1 << 17  # !! Make it configurable in the command line.
    label = 'minifat3'  # !! Make it configurable in the command line.
    uuid = 'DEAD-BEE3'  # !! Make it configurable in the command line.
    rootdir_entry_count = None
    fat_count = None
    fstype = None
    cluster_size = None
    # !! Add command-line flag to create FAT16 24 MiB for SSD alignment.
    fat_header, fatfs_size2 = build_veracrypt_fat(
        decrypted_size, passphrase, do_include_all_header_sectors=True, label=label, uuid=uuid, fatfs_size=fatfs_size, rootdir_entry_count=rootdir_entry_count, fat_count=None, fstype=fstype, cluster_size=cluster_size)
    assert 1536 <= fatfs_size2 <= fatfs_size
    f = open(device, 'wb')
    try:
      f.write(fat_header)
      f.truncate(fatfs_size)
    finally:
      sys.stdout.flush()
    # Mount it like this: sudo veracrypt-console --mount --keyfiles= --protect-hidden=no --pim=485 --filesystem=none --hash=sha512 --encryption=aes fat_disk.img
    # Creates /dev/mapper/veracrypt1 , use this to show the keytable: sudo dmsetup table --showkeys veracrypt1
    # --encryption=aes sems to be ignored, --hash=sha512 is used (because it breaks with --hash=sha256)
    # --pim=485 corresponds to iterations=500000 (https://www.veracrypt.fr/en/Header%20Key%20Derivation.html says that for --hash=sha512 iterations == 15000 + 1000 * pim).
    # For --pim=0, --pim=485 is used with --hash=sha512.
  else:
    print >>sys.stderr, 'fatal: unknown command: %s' % argv[1]
    sys.exit(1)


if __name__ == '__main__':
  sys.exit(main(sys.argv))
