from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
build_options = {
    'packages': ['gi'],
    'excludes': [],
    'include_files': ['gtk.glade'],
    'optimize': 2
}

import sys
base = 'Win32GUI' if sys.platform=='win32' else None

executables = [
    Executable(
        'zenstates.py',
        base=base,
        icon='icon.png'
    )
]

setup(name='zenstates',
      version = '2.0',
      description = '',
      options = {'build_exe': build_options},
      executables = executables)
