import os
try:
    from PIL import ImageGrab
    img = ImageGrab.grab()
    os.makedirs(r"C:\test111", exist_ok=True)
    img.save(r"C:\test111\screenshot.png")
    print("Screenshot saved to C:\\test111\\screenshot.png via PIL")
except Exception as e:
    print(f"PIL error: {e}")
    # Fallback to C# / dotnet or powershell via file
    ps_code = '''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save("C:\\test111\\screenshot.png", [System.Drawing.Imaging.ImageFormat]::Png)
'''
    with open("take_screen.ps1", "w") as f:
        f.write(ps_code)
    os.system("powershell -ExecutionPolicy Bypass -File take_screen.ps1")
    print("Screenshot captured via PowerShell script")
