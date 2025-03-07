# sdnext installer
"""
import installer

dependencies = ['nsfwdetection']
for dependency in dependencies:
    if not installer.installed(dependency, reload=False, quiet=True):
        installer.install(dependency, ignore=False)
"""

# a1111 installer
"""
import launch

for dep in ['nsfwdetection']:
    if not launch.is_installed(dep):
        launch.run_pip(f"install {dep}", f"{dep}")
"""
