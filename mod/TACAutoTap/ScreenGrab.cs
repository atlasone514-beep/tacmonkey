// "shot" for TAC Auto Tap: the frame the game just drew, read inside the game at the end of the
// frame and sent back as a JPEG. TACMonkey asks for it only when Windows won't hand over the
// game's picture (some PCs stop drawing a covered window), so it costs nothing otherwise.
using System;
using System.Globalization;
using UnityEngine;

namespace TACAutoTap;

internal static class ScreenGrab
{
    /// "shot [quality]" -> "ok <width>x<height> <base64 JPEG>". Call at the end of a frame.
    public static string Jpeg(string line)
    {
        var p = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var quality = 70;
        if (p.Length > 1 && int.TryParse(p[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var q))
            quality = Math.Clamp(q, 10, 95);
        int w = Screen.width, h = Screen.height;
        if (w <= 0 || h <= 0) return "err no picture (the window has no size - minimized?)";
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        try
        {
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
            tex.Apply(false);
            var jpg = ImageConversion.EncodeToJPG(tex, quality);
            var bytes = new byte[jpg.Length];
            for (int i = 0; i < bytes.Length; i++) bytes[i] = jpg[i];
            return $"ok {w}x{h} {Convert.ToBase64String(bytes)}";
        }
        finally
        {
            UnityEngine.Object.Destroy(tex);
        }
    }
}
