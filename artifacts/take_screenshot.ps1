Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Screen = [System.Windows.Forms.Screen]::PrimaryScreen
$Width = $Screen.Bounds.Width
$Height = $Screen.Bounds.Height
$Top = $Screen.Bounds.Top
$Left = $Screen.Bounds.Left

$Bitmap = New-Object System.Drawing.Bitmap -ArgumentList $Width, $Height
$Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
$Graphics.CopyFromScreen($Left, $Top, 0, 0, $Bitmap.Size)

$Bitmap.Save("screenshot.png", [System.Drawing.Imaging.ImageFormat]::Png)

$Graphics.Dispose()
$Bitmap.Dispose()
