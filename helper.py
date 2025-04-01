import ctypes
import pathlib
import shutil
import zlib

SPHERE_PATH_MAX = 1024


class SPKHeader(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('signature', ctypes.c_char * 4),
        ('version', ctypes.c_uint16),
        ('num_files', ctypes.c_uint32),
        ('index_offset', ctypes.c_uint32),
        ('reserved', ctypes.c_uint8 * 2)
    ]


class SPKEntryHeader(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('version', ctypes.c_uint16),
        ('filename_size', ctypes.c_uint16),
        ('offset', ctypes.c_uint32),
        ('file_size', ctypes.c_uint32),
        ('compress_size', ctypes.c_uint32)
    ]


def read_ctypes_data(f, struct_type):
    size = ctypes.sizeof(struct_type)
    buffer = f.read(size)
    if len(buffer) != size:
        raise ValueError(f"Failed to read {size} bytes for {struct_type.__name__}")
    return struct_type.from_buffer_copy(buffer)


def extract(spk_path: str | pathlib.Path, dir_path: str | pathlib.Path, overwrite: bool = False):
    spk_path = pathlib.Path(spk_path)
    dir_path = pathlib.Path(dir_path)
    if dir_path.exists():
        if not overwrite:
            raise ValueError(f"Directory {dir_path} already exists")
        shutil.rmtree(dir_path)

    files = []

    dir_path.mkdir(parents=True, exist_ok=True)
    with open(spk_path, 'rb') as f:
        spk_header = read_ctypes_data(f, SPKHeader)
        if spk_header.signature != b'.spk':
            raise ValueError(f"Invalid SPK file signature: {spk_header.signature}")
        if spk_header.version != 1:
            raise ValueError(f"Unsupported SPK version {spk_header.version}")
        offset = spk_header.index_offset
        for i in range(spk_header.num_files):
            f.seek(offset, 0)
            entry_header = read_ctypes_data(f, SPKEntryHeader)
            if entry_header.version != 1:
                raise ValueError(f"Unsupported SPK entry version {entry_header.version} at index {i}")
            filename = f.read(entry_header.filename_size).rstrip(b'\0').decode('utf-8')
            offset += entry_header.filename_size + ctypes.sizeof(SPKEntryHeader)
            print(f"Extracting {filename}: {entry_header.file_size:#X} -> {entry_header.compress_size:#X} at {entry_header.offset:#X}")
            f.seek(entry_header.offset, 0)
            raw = f.read(entry_header.compress_size)
            res = zlib.decompress(raw)
            if len(res) != entry_header.file_size:
                raise ValueError(f"Decompressed size mismatch for {filename}: expected {entry_header.file_size}, got {len(res)}")
            file_path = dir_path / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'wb') as out_f:
                out_f.write(res)
            files.append(filename)

    with open(dir_path / '__files__.txt', 'w') as f:
        f.write('\n'.join(files))


def pack(dir_path: str | pathlib.Path, spk_path: str | pathlib.Path, overwrite: bool = False):
    dir_path = pathlib.Path(dir_path)
    spk_path = pathlib.Path(spk_path)

    if spk_path.exists():
        if not overwrite:
            raise ValueError(f"File {spk_path} already exists")
        spk_path.unlink()
    spk_path.parent.mkdir(parents=True, exist_ok=True)

    if (fp := dir_path / '__files__.txt').exists():
        with open(fp, 'r') as f:
            files = f.read().splitlines()
        files_preset = set(files)
    else:
        files = []
        files_preset = set()

    for file in dir_path.glob('**/*.*'):
        if file.is_file():
            rel_path = file.relative_to(dir_path)
            if rel_path.name == '__files__.txt': continue
            rel_path_s = str(rel_path).replace('\\', '/')
            if rel_path_s in files_preset: continue
            files.append(rel_path_s)

    entries = []
    with open(spk_path, 'wb') as f:
        f.write(SPKHeader())
        for rel_path in files:
            file_path = dir_path / rel_path
            with open(file_path, 'rb') as in_f:
                data = in_f.read()
            compress_data = zlib.compress(data, level=9)
            entries.append(SPKEntryHeader(
                version=1,
                filename_size=len(rel_path.encode('utf-8')) + 1,
                offset=f.tell(),
                file_size=len(data),
                compress_size=len(compress_data)
            ))
            print(f"Packing {rel_path}: {len(data):#X} -> {len(compress_data):#X} to {f.tell():#X}")
            f.write(compress_data)
        index_offset = f.tell()  # write back later
        for rel_path, entry in zip(files, entries):
            f.write(entry)
            f.write(rel_path.encode('utf-8') + b'\0')
        f.seek(0)
        f.write(SPKHeader(
            signature=b'.spk',
            version=1,
            num_files=len(entries),
            index_offset=index_offset
        ))

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="SPK file extractor and packer")
    parser.add_argument('action', choices=['extract', 'pack'], help='Action to perform')
    parser.add_argument('input', help='Input SPK file or directory')
    parser.add_argument('output', help='Output directory or SPK file')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing files')
    args = parser.parse_args()

    if args.action == 'extract':
        extract(args.input, args.output, args.overwrite)
    elif args.action == 'pack':
        pack(args.input, args.output, args.overwrite)