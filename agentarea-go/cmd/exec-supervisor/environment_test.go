package main

import (
	"os/user"
	"slices"
	"testing"
)

func TestCommandEnvironmentGivesTheCommandUserItsOwnHome(t *testing.T) {
	account := &user.User{Uid: "10001", Gid: "10001", Username: "sandbox", HomeDir: "/home/sandbox"}
	inherited := []string{
		"HOME=/root",
		"PATH=/opt/runtime/venv/bin:/usr/bin",
		"USER=root",
		"AGENTAREA_TASK_ID=task-1",
		"LOGNAME=root",
	}

	env, err := commandEnvironment(inherited, account)
	if err != nil {
		t.Fatal(err)
	}

	want := []string{
		"PATH=/opt/runtime/venv/bin:/usr/bin",
		"AGENTAREA_TASK_ID=task-1",
		"HOME=/home/sandbox",
		"USER=sandbox",
		"LOGNAME=sandbox",
	}
	if !slices.Equal(env, want) {
		t.Fatalf("commandEnvironment() = %q, want %q", env, want)
	}
}

func TestCommandEnvironmentRejectsAnAccountWithoutAnAbsoluteHome(t *testing.T) {
	for _, home := range []string{"", "home/sandbox"} {
		account := &user.User{Uid: "10001", Username: "sandbox", HomeDir: home}
		if _, err := commandEnvironment([]string{"HOME=/root"}, account); err == nil {
			t.Fatalf("commandEnvironment() accepted home %q", home)
		}
	}
}
