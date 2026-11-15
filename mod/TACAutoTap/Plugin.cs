// TAC Auto Tap - lets farm.py press game buttons without the Windows mouse.
//
// Listens on 127.0.0.1:47613 (this PC only). One command per line, one reply line each:
//   ping          -> "pong <version> <width>x<height>"
//   tap FX FY     -> press what's at that point; FX/FY = fraction of the window (0..1, from the
//                    top-left). Reply "ok <object path>" if a UI element took the press, or
//                    "nohandler <why>" if nothing there handles presses (farm.py then falls back
//                    to its normal touch tap).
//   probe FX FY   -> same lookup, but only reports what's there; presses nothing.
//   list          -> JSON array of every pressable element on screen: its text, path, centre
//                    (x, y as window fractions from the top-left), size, whether a press would
//                    reach it ("top") and whether it's enabled ("on").
//   click TEXT [#N] -> press the element whose text contains TEXT (case-insensitive), N-th
//                    match in reading order. Replies ok / notfound / blocked.
//   items FX FY   -> every entry of the list under the point (even scrolled out of view), with
//                    its game data fields and picture names, entries separated by " ||| ".
//   inspect FX FY -> the same kind of dump for the object under the point and its parents.
//   scroll FX FY V -> move the list under the point to V (0..1).
// The press is sent through Unity's EventSystem the same way a real touch is: pointer down,
// pointer up, click - on the main thread.
//
// Safety: a web page can make the browser send an HTTP request to 127.0.0.1, and its body would
// arrive here as lines. So the connection is closed at the first line that isn't one of the
// commands above (an HTTP request always starts with "GET/POST ... HTTP/1.1"), before any body
// is read. Lines are also capped in length and must be plain printable ASCII.
using System;
using System.Collections.Concurrent;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using UnityEngine;
using UnityEngine.EventSystems;

namespace TACAutoTap;

[BepInPlugin(Guid, "TAC Auto Tap", Version)]
public class Plugin : BasePlugin
{
    public const string Guid = "tac.autotap";
    public const string Version = "1.2.1";
    public const int Port = 47613;
    private const int MaxLine = 512;
    private static readonly string[] Commands =
        { "ping", "tap", "probe", "list", "click", "items", "inspect", "scroll" };

    internal static ManualLogSource L;
    internal static readonly ConcurrentQueue<Request> Pending = new();

    public override void Load()
    {
        L = Log;
        AddComponent<TapRunner>();
        new Thread(Listen) { IsBackground = true, Name = "TACAutoTap listener" }.Start();
    }

    private static void Listen()
    {
        TcpListener listener;
        try
        {
            listener = new TcpListener(IPAddress.Loopback, Port);
            listener.Start();
            L.LogInfo($"listening on 127.0.0.1:{Port}");
        }
        catch (Exception e)
        {
            L.LogError($"could not listen on 127.0.0.1:{Port}: {e.Message}");
            return;
        }

        while (true)
        {
            try
            {
                using var client = listener.AcceptTcpClient();
                client.NoDelay = true;
                client.ReceiveTimeout = 5000;
                using var stream = client.GetStream();
                var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
                string line;
                while ((line = ReadLine(stream)) != null)
                {
                    line = line.Trim();
                    if (!IsCommand(line))
                    {
                        writer.WriteLine("err not a command - closing");
                        L.LogWarning("closed a connection that sent something other than a command " +
                                     "(e.g. a web page trying to reach the mod)");
                        break;
                    }
                    var req = new Request(line);
                    Pending.Enqueue(req);
                    // The game handles it on its next frame (only ~7 fps when the window isn't focused).
                    writer.WriteLine(req.Done.Wait(3000) ? req.Reply : "err timeout - game busy or paused");
                }
            }
            catch (Exception e)
            {
                L.LogDebug($"connection ended: {e.Message}");
            }
        }
    }

    /// <summary>One line (without the line break), or null at the end of the connection or if
    /// the line is too long or holds anything but printable ASCII.</summary>
    private static string ReadLine(Stream stream)
    {
        var sb = new StringBuilder();
        while (true)
        {
            var b = stream.ReadByte();
            if (b < 0) return sb.Length > 0 ? sb.ToString() : null;
            if (b == '\n') return sb.ToString();
            if (b == '\r') continue;
            if (b < 0x20 || b > 0x7E || sb.Length >= MaxLine) return null;
            sb.Append((char)b);
        }
    }

    private static bool IsCommand(string line)
    {
        if (line.Length == 0 || line.Contains("HTTP/")) return false;
        var space = line.IndexOf(' ');
        var word = space < 0 ? line : line.Substring(0, space);
        return Array.IndexOf(Commands, word) >= 0;
    }
}

internal sealed class Request
{
    public readonly string Line;
    public readonly ManualResetEventSlim Done = new(false);
    public string Reply = "err no reply";
    public Request(string line) => Line = line;
}

public class TapRunner : MonoBehaviour
{
    public TapRunner(IntPtr ptr) : base(ptr) { }

    private void Update()
    {
        while (Plugin.Pending.TryDequeue(out var req))
        {
            try
            {
                req.Reply = Handle(req.Line);
            }
            catch (Exception e)
            {
                req.Reply = $"err {e.GetType().Name}: {e.Message.Replace('\n', ' ')}";
                Plugin.L.LogWarning($"'{req.Line}' failed: {e}");
            }
            req.Done.Set();
        }
    }

    private static string Handle(string line)
    {
        var p = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (p.Length == 0) return "err empty command";
        switch (p[0])
        {
            case "ping":
                return $"pong {Plugin.Version} {Screen.width}x{Screen.height}";
            case "tap":
            case "probe":
                if (p.Length < 3) return "err usage: tap FX FY";
                var fx = float.Parse(p[1], CultureInfo.InvariantCulture);
                var fy = float.Parse(p[2], CultureInfo.InvariantCulture);
                // Unity screen coordinates start at the bottom-left
                var pos = new Vector2(fx * Screen.width, (1f - fy) * Screen.height);
                return Press(pos, p[0] == "tap");
            case "list":
                return UiQuery.ListJson();
            case "items":
            case "inspect":
            case "scroll":
            {
                if (p.Length < 3) return $"err usage: {p[0]} FX FY" + (p[0] == "scroll" ? " V" : "");
                var at = new Vector2(float.Parse(p[1], CultureInfo.InvariantCulture) * Screen.width,
                                     (1f - float.Parse(p[2], CultureInfo.InvariantCulture)) * Screen.height);
                if (p[0] == "items") return UiInspect.Items(at);
                if (p[0] == "inspect") return UiInspect.Inspect(at);
                if (p.Length < 4) return "err usage: scroll FX FY V";
                return UiInspect.Scroll(at, float.Parse(p[3], CultureInfo.InvariantCulture));
            }
            case "click":
                if (p.Length < 2) return "err usage: click <text on the button> [#N]";
                return UiQuery.Click(line.Substring(line.IndexOf(' ') + 1), Press);
            default:
                return "err unknown command";
        }
    }

    private static string Press(Vector2 pos, bool press)
    {
        var es = EventSystem.current;
        if (es == null) return "nohandler no EventSystem";

        var ped = new PointerEventData(es)
        {
            position = pos,
            pressPosition = pos,
            button = PointerEventData.InputButton.Left,
        };
        var results = new Il2CppSystem.Collections.Generic.List<RaycastResult>();
        es.RaycastAll(ped, results);
        if (results.Count == 0) return "nohandler nothing under the point";

        var hit = results[0];
        var target = hit.gameObject;
        ped.pointerCurrentRaycast = hit;
        ped.pointerPressRaycast = hit;

        var downHandler = ExecuteEvents.GetEventHandler<IPointerDownHandler>(target);
        var clickHandler = ExecuteEvents.GetEventHandler<IPointerClickHandler>(target);
        var handler = downHandler != null ? downHandler : clickHandler;
        if (handler == null) return $"nohandler {PathOf(target)} takes no presses";
        if (!press) return $"ok {PathOf(handler)} (probe only)";

        // Same order as Unity's input module: down, up, click
        var pressed = ExecuteEvents.ExecuteHierarchy(target, ped, ExecuteEvents.pointerDownHandler);
        if (pressed == null) pressed = clickHandler;
        ped.pointerPress = pressed;
        ped.rawPointerPress = target;
        ped.eligibleForClick = true;
        ped.clickCount = 1;
        ped.clickTime = Time.unscaledTime;
        ExecuteEvents.Execute(pressed, ped, ExecuteEvents.pointerUpHandler);
        if (clickHandler != null && pressed != null && clickHandler.Pointer == pressed.Pointer)
            ExecuteEvents.Execute(clickHandler, ped, ExecuteEvents.pointerClickHandler);
        return $"ok {PathOf(pressed)}";
    }

    internal static string PathOfPublic(GameObject go) => PathOf(go);

    private static string PathOf(GameObject go)
    {
        if (go == null) return "(none)";
        var path = go.name;
        var t = go.transform.parent;
        for (int i = 0; t != null && i < 6; i++, t = t.parent) path = t.name + "/" + path;
        return path.Replace(' ', '_');
    }
}
