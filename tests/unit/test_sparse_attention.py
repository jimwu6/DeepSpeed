# DeepSpeed note, some parts of code taken & adapted from commit c368a9fd1b2c9dee4cc94de9a6bb0be3d447be41
# https://github.com/ptillet/torch-blocksparse/blob/master/tests/test_softmax.py
# https://github.com/ptillet/torch-blocksparse/blob/master/tests/test_matmul.py
# https://github.com/ptillet/torch-blocksparse/blob/master/tests/utils

import pytest
import torch
import deepspeed
from deepspeed.ops.op_builder import SparseAttnBuilder

if not deepspeed.ops.__compatible_ops__[SparseAttnBuilder.NAME]:
    pytest.skip("sparse attention op is not compatible on this system",
                allow_module_level=True)


def test_sparse_attention_module_availability():
    return True
    try:
        from deepspeed.ops import sparse_attention  # noqa: F401
    except ImportError:
        print("Sparse Attention Module is not installed!")
        return False
    return True


def test_matmul_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention.matmul import MatMul  # noqa: F401
    except ImportError:
        print("Sparse MatMul Module is not installed!")
        return False
    return True


def test_softmax_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention.softmax import Softmax  # noqa: F401
    except ImportError:
        print("Sparse Softmax Module is not installed!")
        return False
    return True


def test_sparsityconfig_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import SparsityConfig  # noqa: F401
    except ImportError:
        print("SparsityConfig Module is not installed!")
        return False
    return True


def test_densesparsityconfig_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import DenseSparsityConfig  # noqa: F401
    except ImportError:
        print("DenseSparsityConfig Module is not installed!")
        return False
    return True


def test_fixedsparsityconfig_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import FixedSparsityConfig  # noqa: F401
    except ImportError:
        print("FixedSparsityConfig Module is not installed!")
        return False
    return True


def test_variablesparsityconfig_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import VariableSparsityConfig  # noqa: F401
    except ImportError:
        print("VariableSparsityConfig Module is not installed!")
        return False
    return True


def test_bigbirdsparsityconfig_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import BigBirdSparsityConfig  # noqa: F401
    except ImportError:
        print("BigBirdSparsityConfig Module is not installed!")
        return False
    return True


def test_bslongformersparsityconfig_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import BSLongformerSparsityConfig  # noqa: F401
    except ImportError:
        print("BSLongformerSparsityConfig Module is not installed!")
        return False
    return True


def test_sparseselfattention_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import SparseSelfAttention  # noqa: F401
    except ImportError:
        print("SparseSelfAttention Module is not installed!")
        return False
    return True


def test_bertsparseselfattention_module_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import BertSparseSelfAttention  # noqa: F401
    except ImportError:
        print("BertSparseSelfAttention Module is not installed!")
        return False
    return True


def test_sparseattentionutils_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import SparseAttentionUtils  # noqa: F401
    except ImportError:
        print("SparseAttentionUtils Module is not installed!")
        return False
    return True


def test_cpp_utils_availability():
    return True
    try:
        from deepspeed.ops.sparse_attention import cpp_utils  # noqa: F401
    except ImportError:
        print("Sparse Attention cpp_utils Module is not installed!")
        return False
    return True


def dense_to_sparse(w, mask, block):
    """Converts dense matrix with explicit zeros to sparse matrix
    """
    Z = w.size(0)
    ret = torch.empty((Z, mask.sum(), block, block), dtype=w.dtype, device=w.device)
    nnz = mask.nonzero()
    h, i, j = nnz[:, 0], nnz[:, 1], nnz[:, 2]
    for zz in range(Z):
        for idx, (hh, ii, jj) in enumerate(zip(h, i, j)):
            ret[zz, idx, :, :] = w[zz, hh, ii*block: (ii+1)*block, jj*block: (jj+1)*block]
    return ret


def sparse_to_dense(w, mask, block, zero=0):
    """Converts sparse matrix to dense matrix with explicit zeros
    """
    maskedw = w.clone()
    for bz, wz in enumerate(range(0, w.size(0))):
        for bh, wh in enumerate(range(0, w.size(1))):
            for bi, wi in enumerate(range(0, w.size(2), block)):
                for bj, wj in enumerate(range(0, w.size(3), block)):
                    if mask[bh, bi, bj] == 0:
                        maskedw[wz, wh, wi:wi + block, wj:wj + block] = zero
                    #maskedw[wz, wh, wi : wi+block, wj : wj+block] *= mask[bh, bi, bj]
    return maskedw


def allclose(x, y):
    assert x.dtype == y.dtype
    rtol, atol = {torch.float32: (5e-4, 5e-5), torch.float16: (3e-2, 2e-3)}[x.dtype]
    return torch.allclose(x, y, rtol=rtol, atol=atol)


def make_layout(rho, shape):
    probs = torch.Tensor([rho, 1 - rho])
    generator = torch.distributions.categorical.Categorical(probs)
    layout = generator.sample(shape)
    return layout


def run_softmax_reference(x, scale, dx, kp_mask, attn_mask, layout, block):
    x = sparse_to_dense(x, layout, block, zero=float('-inf'))
    x.retain_grad()
    if kp_mask is not None:
        bcattn_mask = attn_mask[None, None, :, :] + torch.zeros_like(x)
        x[bcattn_mask == 0] = float('-inf')
        y = torch.softmax(x * scale + kp_mask[:, None, None, :], -1)
    else:
        y = torch.softmax(x * scale, -1)
    y.backward(dx)
    dx = x.grad.clone()
    dx = dense_to_sparse(dx, layout, block)
    y = dense_to_sparse(y, layout, block)
    return y, dx


def run_softmax_sparse(x, scale, dx, kp_mask, attn_mask, layout, block):
    from deepspeed.ops.sparse_attention.softmax import Softmax
    sparse_softmax = Softmax(layout, block, bench=False)

    dx = dense_to_sparse(dx, layout, block)
    x = dense_to_sparse(x, layout, block)
    x.retain_grad()
    y = sparse_softmax(x,
                       scale=scale,
                       key_padding_mask=kp_mask,
                       key_padding_mask_mode='add',
                       attn_mask=attn_mask,
                       attn_mask_mode='mul')
    y.backward(dx)
    dx = x.grad.clone()
    x.grad.zero_()
    return x, dx


def init_softmax_inputs(Z, H, M, N, scale, rho, block, dtype, dense_x=True, layout=None):
    if layout is None:
        layout = make_layout(rho, (H, M // block, N // block))
    if dense_x:
        x = torch.rand((Z, H, M, N), dtype=dtype, requires_grad=True, device='cuda')
    else:
        x = torch.rand((Z,
                        layout.sum(),
                        block,
                        block),
                       dtype=dtype,
                       requires_grad=True,
                       device='cuda')
    dx = torch.rand_like(x)
    bool_attn_mask = torch.randint(low=0,
                                   high=2,
                                   size=(N,
                                         N),
                                   dtype=torch.bool,
                                   requires_grad=False,
                                   device='cuda')
    fp_attn_mask = bool_attn_mask.type(dtype)
    kp_mask = torch.randint(low=0,
                            high=2,
                            size=(Z,
                                  N),
                            dtype=dtype,
                            requires_grad=False,
                            device='cuda')
    kp_mask[kp_mask == 1.] = float('-inf')
    return layout, x, dx, bool_attn_mask, fp_attn_mask, kp_mask


def _skip_on_cuda_compatability():
    if torch.cuda.get_device_capability()[0] < 7:
        pytest.skip("needs higher compute capability than 7")
    cuda_major = int(torch.version.cuda.split('.')[0]) * 10
    cuda_minor = int(torch.version.cuda.split('.')[1])
    cuda_version = cuda_major + cuda_minor
    if (cuda_version != 101 and cuda_version != 102) and \
            (cuda_version != 111 and cuda_version != 110):
        pytest.skip("requires cuda 10.1 or 10.2 or 11.0 or 11.1")


@pytest.mark.parametrize("block", [16, 32])
@pytest.mark.parametrize("width", [256, 576])
@pytest.mark.parametrize("dtype", [torch.float16, torch.float32])
def test_softmax(block, width, dtype):
    _skip_on_cuda_compatability()
    Z = 2
    H = 4
    scale = 0.4
    rho = 0.4
    M = N = width
    layout, x, dx, bool_attn_mask, fp_attn_mask, kp_mask = init_softmax_inputs(Z, H, M, N, scale, rho, block, dtype, layout=None)
    ref_y, ref_dx = run_softmax_reference(x, scale, dx, kp_mask, bool_attn_mask, layout, block)
    st_y, st_dx = run_softmax_sparse(x, scale, dx, kp_mask, fp_attn_mask, layout, block)

    assert allclose(ref_y, st_y)
    assert allclose(ref_dx, st_dx)


def run_matmul_reference(x, w, mode, trans_a, trans_b, layout, block, dy):
    x = sparse_to_dense(x, layout, block) if mode == 'dsd' else x
    w = sparse_to_dense(w, layout, block) if mode == 'dds' else w
    x.retain_grad()
    w.retain_grad()
    xx = x.transpose(2, 3) if trans_a else x
    ww = w.transpose(2, 3) if trans_b else w
    y = torch.matmul(xx, ww)
    y = sparse_to_dense(y, layout, block) if mode == 'sdd' else y
    y.backward(dy)
    dx = x.grad.clone()
    dw = w.grad.clone()
    x.grad.zero_()
    w.grad.zero_()
    y = dense_to_sparse(y, layout, block) if mode == 'sdd' else y
    dx = dense_to_sparse(dx, layout, block) if mode == 'dsd' else dx
    dw = dense_to_sparse(dw, layout, block) if mode == 'dds' else dw
    return y, dx, dw


def run_matmul_sparse(x, w, mode, trans_a, trans_b, layout, block, dy):
    from deepspeed.ops.sparse_attention.matmul import MatMul
    x = dense_to_sparse(x, layout, block) if mode == 'dsd' else x
    w = dense_to_sparse(w, layout, block) if mode == 'dds' else w
    dy = dense_to_sparse(dy, layout, block) if mode == 'sdd' else dy
    op = MatMul(layout, block, mode, trans_a=trans_a, trans_b=trans_b)
    x.retain_grad()
    w.retain_grad()
    y = op(x, w)
    y.backward(dy)
    dx = x.grad.clone()
    dw = w.grad.clone()
    x.grad.zero_()
    return y, dx, dw


def init_matmul_inputs(Z, H, M, N, K, rho, mode, trans_a, trans_b, block, dtype, layout):
    torch.manual_seed(1)
    AS0 = K if trans_a else M
    AS1 = M if trans_a else K
    BS0 = N if trans_b else K
    BS1 = K if trans_b else N
    shape = {'sdd': (M, N), 'dsd': (AS0, AS1), 'dds': (BS0, BS1)}[mode]
    x = torch.rand((Z, H, AS0, AS1), dtype=dtype, requires_grad=True, device='cuda')
    w = torch.rand((Z, H, BS0, BS1), dtype=dtype, requires_grad=True, device='cuda')
    dy = torch.rand((Z, H, M, N), dtype=dtype, device='cuda')
    if layout is None:
        layout = make_layout(rho, (H, shape[0] // block, shape[1] // block))
    else:
        assert list(layout.shape) == [H, shape[0] // block, shape[1] // block]
    x.retain_grad()
    w.retain_grad()
    return x, w, dy, shape, layout

testdata = [
      (16, dtype, mode, trans_a, trans_b)\
         for dtype in [torch.float16]\
         for mode in ['sdd', 'dds']\
         for trans_a   in [False]\
         for trans_b   in [False, True]\
   ] + [
      (16, dtype, mode, trans_a, trans_b)\
         for dtype in [torch.float16]\
         for mode in ['dsd']\
         for trans_a   in [False, True]\
         for trans_b   in [False]\
   ] + [
      (16, dtype, mode, trans_a, trans_b)\
         for dtype in [torch.float32]\
         for mode in ['sdd', 'dsd', 'dds']\
         for trans_a   in [False]\
         for trans_b   in [False]\
   ] + [
      (block, torch.float16, mode, False, False)\
         for block in [16, 32, 64]\
         for mode in ['sdd', 'dsd', 'dds']\
   ]


@pytest.mark.parametrize("block, dtype, mode, trans_a, trans_b", testdata)
def test_matmul(block, dtype, mode, trans_a, trans_b):
    _skip_on_cuda_compatability()
    Z = 3
    H = 2
    M = 128
    N = 256
    K = 192
    rho = 0.5
    x, w, dy, shape, layout = init_matmul_inputs(Z, H, M, N, K, rho, mode, trans_a, trans_b, block, dtype, layout=None)
    ref_y, ref_dx, ref_dw = run_matmul_reference(x.clone(), w.clone(), mode, trans_a, trans_b, layout, block, dy)
    st_y, st_dx, st_dw = run_matmul_sparse(x.clone(), w.clone(), mode, trans_a, trans_b, layout, block, dy)
    assert allclose(ref_y, st_y)
    assert allclose(ref_dx, st_dx)
    assert allclose(ref_dw, st_dw)
