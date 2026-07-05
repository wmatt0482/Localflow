from localflow import textproc


def test_new_line_command():
    assert textproc.process("Hello. New line. World") == "Hello.\nWorld"


def test_new_paragraph_command():
    assert textproc.process("First part new paragraph second part") == (
        "First part\n\nsecond part"
    )


def test_voice_commands_case_insensitive():
    assert textproc.process("a NEW LINE b") == "a\nb"


def test_voice_commands_disabled():
    out = textproc.process("Hello new line world", voice_commands=False)
    assert out == "Hello new line world"


def test_newline_not_matched_inside_words():
    # "newline" as a single word is not the spoken command
    assert textproc.process("the newline character") == "the newline character"


def test_replacements_case_insensitive_whole_word():
    out = textproc.process(
        "i use local flow daily", replacements={"local flow": "LocalFlow"}
    )
    assert out == "i use LocalFlow daily"


def test_replacement_not_partial_word():
    out = textproc.process("the cathode", replacements={"cat": "dog"})
    assert out == "the cathode"


def test_trailing_space():
    assert textproc.process("hello", trailing_space=True) == "hello "


def test_trailing_space_empty_text():
    assert textproc.process("", trailing_space=True) == ""


def test_whitespace_collapsed():
    assert textproc.process("a  b   c") == "a b c"
