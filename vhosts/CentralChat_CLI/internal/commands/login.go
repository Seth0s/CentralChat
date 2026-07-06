package commands

import (
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/auth"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/spf13/cobra"
)

func loginCmd() *cobra.Command {
	var email, password, apiURL, apiKey string
	var useDevice bool
	cmd := &cobra.Command{
		Use:   "login",
		Short: "Authenticate and save credentials (password, device code, or API key)",
		Run: func(cmd *cobra.Command, args []string) {
			cfg, err := config.Load()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if apiURL == "" {
				apiURL = cfg.APIURL
			}
			client := api.New(apiURL, "")

			var resp *api.LoginResponse
			if apiKey != "" {
				resp, err = client.ExchangeApiKey(apiKey)
				if err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
			} else if useDevice {
				start, err := client.StartDeviceAuth("central-cli")
				if err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				userCode, _ := start["user_code"].(string)
				fmt.Printf("Approve login with code: %s\n", userCode)
				fmt.Printf("Web: %s/login (ou POST /auth/device/approve com email/password)\n", strings.TrimRight(apiURL, "/8004"))
				interval := 5
				if v, ok := start["interval"].(float64); ok && v > 0 {
					interval = int(v)
				}
				deviceCode, _ := start["device_code"].(string)
				deadline := time.Now().Add(10 * time.Minute)
				for time.Now().Before(deadline) {
					resp, err = client.PollDeviceToken(deviceCode)
					if err == nil {
						break
					}
					if !strings.Contains(err.Error(), "428") && !strings.Contains(err.Error(), "authorization_pending") {
						fmt.Fprintln(os.Stderr, err)
						os.Exit(1)
					}
					time.Sleep(time.Duration(interval) * time.Second)
				}
				if resp == nil {
					fmt.Fprintln(os.Stderr, "device login expirou ou foi negado")
					os.Exit(1)
				}
			} else {
				if email == "" {
					fmt.Fprint(os.Stderr, "Email: ")
					fmt.Fscanln(os.Stdin, &email)
				}
				if password == "" {
					fmt.Fprint(os.Stderr, "Password: ")
					fmt.Fscanln(os.Stdin, &password)
				}
				resp, err = client.Login(email, password)
				if err != nil {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
			}

			credPath, err := config.CredentialsPath()
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if err := auth.Save(credPath, &auth.Credentials{
				AccessToken:  resp.AccessToken,
				RefreshToken: resp.RefreshToken,
				APIURL:       apiURL,
			}); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			fmt.Printf("Logged in. Credentials: %s\n", credPath)
		},
	}
	cmd.Flags().StringVar(&email, "email", "", "login email")
	cmd.Flags().StringVar(&password, "password", "", "password")
	cmd.Flags().StringVar(&apiURL, "api", "", "API base URL")
	cmd.Flags().StringVar(&apiKey, "api-key", "", "API key (ck_...)")
	cmd.Flags().BoolVar(&useDevice, "device", false, "OAuth2 device code flow")
	return cmd
}
